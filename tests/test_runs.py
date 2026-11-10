import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from bi_wiki.core.errors import InvalidTransition, RunConflict, RunNotFound
from bi_wiki.db.models import RunORM
from bi_wiki.models.runs import RunError, RunStatus, WorkflowType
from bi_wiki.repositories.runs import RunRepository


async def test_creates_and_reads_real_postgresql_record(database):
    _, db = database
    repo = RunRepository(db.sessions)
    created = await repo.create(WorkflowType.QUERY)
    assert created.status == RunStatus.QUEUED
    assert created.stage == "registered"
    assert created.started_at is None and created.completed_at is None
    assert created.created_at.utcoffset().total_seconds() == 0
    assert await repo.get(created.run_id) == created


async def test_unknown_record(database):
    _, db = database
    with pytest.raises(RunNotFound):
        await RunRepository(db.sessions).get(uuid4())


async def test_transitions_preserve_start_and_persist_error(database):
    _, db = database
    repo = RunRepository(db.sessions)
    queued = await repo.create(WorkflowType.INGEST)
    running = await repo.transition(
        queued.run_id, RunStatus.RUNNING, expected_version=1, stage="preparing"
    )
    waiting = await repo.transition(
        queued.run_id, RunStatus.AWAITING_APPROVAL, expected_version=2, stage="review"
    )
    resumed = await repo.transition(
        queued.run_id, RunStatus.RUNNING, expected_version=3, stage="applying"
    )
    failed = await repo.transition(
        queued.run_id,
        RunStatus.FAILED,
        expected_version=4,
        stage="apply_failed",
        error=RunError(code="TEST_FAILURE", message="deterministic fixture"),
    )
    assert waiting.started_at == running.started_at == resumed.started_at == failed.started_at
    assert failed.completed_at is not None
    assert (await repo.get(queued.run_id)).error.code == "TEST_FAILURE"
    with pytest.raises(InvalidTransition):
        await repo.transition(queued.run_id, RunStatus.SUCCEEDED, expected_version=5, stage="done")


async def test_rejects_skipped_execution_and_non_ingest_approval(database):
    _, db = database
    repo = RunRepository(db.sessions)
    queued = await repo.create(WorkflowType.QUERY)
    with pytest.raises(InvalidTransition):
        await repo.transition(queued.run_id, RunStatus.SUCCEEDED, expected_version=1, stage="done")
    await repo.transition(queued.run_id, RunStatus.RUNNING, expected_version=1, stage="querying")
    with pytest.raises(InvalidTransition):
        await repo.transition(
            queued.run_id, RunStatus.AWAITING_APPROVAL, expected_version=2, stage="review"
        )
    with pytest.raises(InvalidTransition):
        await repo.transition(queued.run_id, RunStatus.FAILED, expected_version=2, stage="failed")


async def test_concurrent_state_updates_do_not_overwrite(database):
    _, db = database
    repo = RunRepository(db.sessions)
    queued = await repo.create(WorkflowType.LINT)
    outcomes = await asyncio.gather(
        repo.transition(queued.run_id, RunStatus.RUNNING, expected_version=1, stage="linting"),
        repo.transition(queued.run_id, RunStatus.CANCELLED, expected_version=1, stage="cancelled"),
        return_exceptions=True,
    )
    assert sum(isinstance(item, RunConflict) for item in outcomes) == 1
    assert (await repo.get(queued.run_id)).version == 2


async def test_success_and_cancel_timestamps(database):
    _, db = database
    repo = RunRepository(db.sessions)
    queued = await repo.create(WorkflowType.QUERY)
    await repo.transition(queued.run_id, RunStatus.RUNNING, expected_version=1, stage="querying")
    done = await repo.transition(
        queued.run_id,
        RunStatus.SUCCEEDED,
        expected_version=2,
        stage="done",
        result_ref="report:test",
    )
    assert done.completed_at >= done.started_at >= done.created_at
    assert done.result_ref == "report:test"
    cancelled = await repo.create(WorkflowType.LINT)
    result = await repo.transition(
        cancelled.run_id, RunStatus.CANCELLED, expected_version=1, stage="cancelled"
    )
    assert result.started_at is None and result.completed_at is not None


async def test_database_rejects_invalid_status(database):
    _, db = database
    with pytest.raises(IntegrityError):
        async with db.sessions.begin() as session:
            await session.execute(insert(RunORM).values(workflow_type="query", status="imaginary"))
