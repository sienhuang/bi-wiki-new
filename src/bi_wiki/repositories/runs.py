from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bi_wiki.core.errors import InvalidTransition, RunConflict, RunNotFound
from bi_wiki.core.logging import logger
from bi_wiki.db.models import RunORM, utc_now
from bi_wiki.models.runs import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    RunError,
    RunRead,
    RunStatus,
    WorkflowType,
)


class RunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(self, workflow_type: WorkflowType) -> RunRead:
        async with self.sessions.begin() as session:
            run = RunORM(workflow_type=workflow_type.value)
            session.add(run)
            await session.flush()
            result = RunRead.model_validate(run)
        logger.info(
            "run_registered",
            extra={
                "run_id": str(result.run_id),
                "workflow": result.workflow_type.value,
                "stage": result.stage,
                "status": result.status.value,
            },
        )
        return result

    async def get(self, run_id: UUID) -> RunRead:
        async with self.sessions() as session:
            run = await session.get(RunORM, run_id)
            if run is None:
                raise RunNotFound()
            return RunRead.model_validate(run)

    async def transition(
        self,
        run_id: UUID,
        target: RunStatus,
        *,
        expected_version: int,
        stage: str,
        result_ref: str | None = None,
        error: RunError | None = None,
    ) -> RunRead:
        """内部运行时入口；第一阶段没有暴露任何 HTTP 状态修改接口。

        状态和版本在同一 UPDATE 中比较，防止并发执行者覆盖彼此的状态。
        终态不可重开；审批行为由后续工作流实现，不能靠修改一个状态冒充批准。
        """
        current = await self.get(run_id)
        if current.version != expected_version:
            raise RunConflict()
        if target not in ALLOWED_TRANSITIONS.get(current.status, set()):
            raise InvalidTransition()
        if target == RunStatus.AWAITING_APPROVAL and current.workflow_type != WorkflowType.INGEST:
            raise InvalidTransition()
        if (target == RunStatus.FAILED) != (error is not None):
            raise InvalidTransition()
        if not stage or len(stage) > 64:
            raise InvalidTransition()
        now = utc_now()
        async with self.sessions.begin() as session:
            statement = (
                update(RunORM)
                .where(
                    RunORM.run_id == run_id,
                    RunORM.version == expected_version,
                    RunORM.status == current.status.value,
                )
                .values(
                    status=target.value,
                    stage=stage,
                    version=expected_version + 1,
                    updated_at=now,
                    started_at=current.started_at or (now if target == RunStatus.RUNNING else None),
                    completed_at=now if target in TERMINAL_STATUSES else None,
                    result_ref=result_ref,
                    error=error.model_dump() if error else None,
                )
                .returning(RunORM)
            )
            changed = (await session.execute(statement)).scalar_one_or_none()
            if changed is None:
                raise RunConflict()
            result = RunRead.model_validate(changed)
        logger.info(
            "run_transitioned",
            extra={
                "run_id": str(result.run_id),
                "workflow": result.workflow_type.value,
                "stage": result.stage,
                "status": result.status.value,
            },
        )
        return result
