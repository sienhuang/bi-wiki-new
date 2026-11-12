"""Fixed workflow, immutable plans, owner-scoped atomic publication."""

import asyncio
import base64
import binascii
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text

from bi_wiki.core.errors import ServiceError
from bi_wiki.core.logging import log_context, logger
from bi_wiki.db.models import RunORM, utc_now
from bi_wiki.ingest.models import Extraction, SourceRead, WorkflowConfig
from bi_wiki.ingest.raw import RawStorage
from bi_wiki.ingest.tables import (
    ConfigORM,
    DefinitionORM,
    IngestORM,
    RequestORM,
    RevisionORM,
    SourceORM,
)
from bi_wiki.models.runs import RunRead


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def change_state(run, status, stage, error=None):
    run.status, run.stage, run.error = status, stage, error
    run.version += 1
    run.updated_at = utc_now()
    run.started_at = run.started_at or utc_now()
    run.completed_at = utc_now() if status in {"succeeded", "failed", "cancelled"} else None


def definition_view(row):
    return {
        "id": str(row.id),
        "version": row.version,
        "key": row.key,
        "data": row.data,
        "markdown": row.markdown,
        "updated_at": row.updated_at.isoformat(),
    }


def render_markdown(data):
    lines = [
        f"# {data['name']}",
        "",
        data["definition"],
        "",
        f"适用范围：{data['scope']}",
        "",
        "## 属性",
    ]
    lines.extend(f"- {k}：{v}" for k, v in data["attributes"].items())
    lines.extend(["", "## 未明确事项", *[f"- {v}" for v in data["unknowns"]], "", "## 关系"])
    lines.extend(f"- {r['type']} → {r['target_key']}" for r in data["relations"])
    lines.extend(["", "## 来源证据", f"来源：{data['source_id']} / SHA-256 {data['source_hash']}"])
    lines.extend(
        f"- 第 {e['start_line']}–{e['end_line']} 行：{e['quote']}" for e in data["evidence"]
    )
    return "\n".join(lines)


def check_candidates(extraction, source_text, config, existing):
    """Deterministic structure/evidence checks; NOT a truth/entailment judge."""
    errors, warnings = [], []
    lines = source_text.splitlines()
    keys = [c.key for c in extraction.candidates]
    known = {d.key: d.data["kind"] for d in existing}
    known.update({c.key: c.kind for c in extraction.candidates})
    if len(set(keys)) != len(keys):
        errors.append("候选知识 key 重复")
    if len(keys) > config["max_candidates"]:
        errors.append("候选数量超过配置限制")
    targets = [str(c.target_id) for c in extraction.candidates if c.target_id]
    if len(set(targets)) != len(targets):
        errors.append("同一定义不能在一个计划内修改多次")
    by_id = {d.id: d for d in existing}
    by_key = {d.key: d for d in existing}
    for c in extraction.candidates:
        if c.kind not in config["kinds"]:
            errors.append(f"{c.key}：类型不在提取范围")
        if c.target_id and (
            c.target_id not in by_id
            or by_id[c.target_id].key != c.key
            or by_id[c.target_id].data["kind"] != c.kind
        ):
            errors.append(f"{c.key}：目标不存在或试图改名/改类型")
        if not c.target_id and c.key in by_key:
            errors.append(f"{c.key}：标识已存在，需要人工确认是否为同一定义")
        for e in [*c.evidence, *[r.evidence for r in c.relations]]:
            excerpt = "\n".join(lines[e.start_line - 1 : e.end_line])
            if e.end_line < e.start_line or e.end_line > len(lines) or e.quote not in excerpt:
                errors.append(f"{c.key}：证据片段与原文行号不匹配")
        if any(len(k) > 100 or len(v) > 4000 for k, v in c.attributes.items()):
            errors.append(f"{c.key}：属性过长")
        for r in c.relations:
            target_kind = known.get(r.target_key)
            if target_kind is None:
                errors.append(f"{c.key}：关系目标 {r.target_key} 不存在")
            if r.type == "measures" and (c.kind != "metric" or target_kind != "entity"):
                errors.append(f"{c.key}：measures 必须从指标指向业务对象")
            if r.type == "constrained_by" and target_kind != "rule":
                errors.append(f"{c.key}：constrained_by 必须指向规则")
            if r.type == "maps_to" and target_kind != "data_asset":
                errors.append(f"{c.key}：maps_to 必须指向数据资产")
        if c.unknowns:
            warnings.append(f"{c.key}：存在 {len(c.unknowns)} 项未明确内容，不能视为可执行计算定义")
    if not keys:
        warnings.append("没有提取到有证据的候选知识")
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "semantic_status": "NOT_RUN",
        "note": "仅验证结构、引用和原文匹配；语义正确性由审核人确认",
    }


class IngestService:
    def __init__(self, sessions, raw: RawStorage, extractor, *, timeouts=None):
        self.sessions, self.raw, self.extractor = sessions, raw, extractor
        self.timeouts = timeouts or {
            "model_seconds": 300,
            "execution_seconds": 330,
            "recovery_seconds": 390,
            "client_seconds": 360,
        }

    async def lock(self, session, owner):
        # Scoped transaction lock serializes mutations across processes for this workspace.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner, 0))"),
            {"owner": "ontology:" + owner},
        )

    async def source(self, session, owner, source_id):
        row = await session.get(SourceORM, source_id)
        if row is None or row.owner != owner:
            raise ServiceError("SOURCE_NOT_FOUND", "来源不存在", 404)
        return row

    async def upload(self, owner, body):
        if (
            Path(body.filename).name != body.filename
            or "\\" in body.filename
            or any(ord(c) < 32 for c in body.filename)
        ):
            raise ServiceError("INVALID_FILENAME", "文件名不能包含路径或控制字符", 422)
        if Path(body.filename).suffix.lower() not in {".md", ".txt"}:
            raise ServiceError("UNSUPPORTED_FORMAT", "首版仅支持 UTF-8 Markdown 和 TXT", 415)
        try:
            raw = base64.b64decode(body.content_base64, validate=True)
            content = raw.decode("utf-8-sig")
        except (ValueError, binascii.Error, UnicodeError):
            raise ServiceError("INVALID_SOURCE", "文件必须为有效的 UTF-8 文本", 422) from None
        if (
            not raw
            or len(raw) > 131072
            or len(content) > 1600000
            or "\x00" in content
            or not content.strip()
        ):
            raise ServiceError("SOURCE_LIMIT", "资料需为非空文本，最多 128 KiB、60000 字符", 413)
        sha = hashlib.sha256(raw).hexdigest()
        async with self.sessions.begin() as session:
            await self.lock(session, owner)
            row = await session.scalar(
                select(SourceORM).where(SourceORM.owner == owner, SourceORM.sha256 == sha)
            )
            if row:
                return {"source": SourceRead.model_validate(row), "duplicate": True}
            # Raw persists even if metadata transaction later fails. Retry reconciles same hash.
            await asyncio.to_thread(self.raw.put, owner, raw)
            row = SourceORM(owner=owner, filename=body.filename, sha256=sha, size_bytes=len(raw))
            session.add(row)
            await session.flush()
            return {"source": SourceRead.model_validate(row), "duplicate": False}

    async def list_sources(self, owner):
        async with self.sessions() as session:
            rows = await session.scalars(
                select(SourceORM)
                .where(SourceORM.owner == owner)
                .order_by(SourceORM.created_at.desc())
                .limit(200)
            )
            return [SourceRead.model_validate(r) for r in rows]

    async def read_source(self, owner, source_id):
        async with self.sessions() as session:
            row = await self.source(session, owner, source_id)
            data = await asyncio.to_thread(self.raw.read, owner, row.sha256)
            return {"source": SourceRead.model_validate(row), "text": data.decode("utf-8-sig")}

    async def config(self, owner, session=None):
        if session is None:
            async with self.sessions() as s:
                return await self.config(owner, s)
        row = await session.scalar(
            select(ConfigORM)
            .where(ConfigORM.owner == owner)
            .order_by(ConfigORM.version.desc())
            .limit(1)
        )
        return {
            "version": row.version if row else 0,
            "body": row.body if row else WorkflowConfig().model_dump(),
            "schema_version": "ontology-v1",
            "workflow_version": "document-v1",
            "model_ready": self.extractor.ready,
            "timeouts": self.timeouts,
        }

    async def save_config(self, owner, body):
        async with self.sessions.begin() as session:
            await self.lock(session, owner)
            current = await self.config(owner, session)
            row = ConfigORM(owner=owner, version=current["version"] + 1, body=body.model_dump())
            session.add(row)
            await session.flush()
            return await self.config(owner, session)

    async def _owned(self, session, owner, run_id, for_update=False):
        query = select(IngestORM).where(IngestORM.run_id == run_id, IngestORM.owner == owner)
        if for_update:
            query = query.with_for_update()
        row = await session.scalar(query)
        if row is None:
            raise ServiceError("INGEST_NOT_FOUND", "导入任务不存在", 404)
        return row

    async def recover(self, owner):
        # Request-driven reconciliation; a crashed process cannot leave permanent running records.
        async with self.sessions.begin() as session:
            rows = await session.execute(
                select(IngestORM, RunORM)
                .join(RunORM)
                .where(
                    IngestORM.owner == owner,
                    RunORM.status == "running",
                )
                .with_for_update()
            )
            for ingest, run in rows:
                recovery = ingest.config.get("timeouts", self.timeouts)["recovery_seconds"]
                if run.updated_at >= utc_now() - timedelta(seconds=recovery):
                    continue
                change_state(
                    run,
                    "failed",
                    "interrupted",
                    {
                        "code": "EXECUTION_INTERRUPTED",
                        "message": "执行超时或进程中断；原始资料保留，可重新生成计划",
                    },
                )

    async def detail(self, owner, run_id):
        await self.recover(owner)
        async with self.sessions() as session:
            row = await self._owned(session, owner, run_id)
            run = await session.get(RunORM, run_id)
            source = await self.source(session, owner, row.source_id)
            return {
                "run": RunRead.model_validate(run),
                "source": SourceRead.model_validate(source),
                "config": row.config,
                "plan": row.plan,
                "plan_hash": row.plan_hash,
                "decision": row.decision,
                "publication_errors": row.publication_errors,
            }

    async def by_request(self, owner, key):
        async with self.sessions() as session:
            request = await session.get(RequestORM, (owner, key))
            if request is None:
                raise ServiceError(
                    "INGEST_REQUEST_NOT_FOUND", "尚未查到该请求，请稍后查看任务列表", 404
                )
            run_id = request.run_id
        return await self.detail(owner, run_id)

    async def list_runs(self, owner):
        await self.recover(owner)
        async with self.sessions() as session:
            rows = await session.execute(
                select(IngestORM, RunORM, SourceORM)
                .join(RunORM)
                .join(SourceORM, IngestORM.source_id == SourceORM.id)
                .where(IngestORM.owner == owner)
                .order_by(IngestORM.created_at.desc())
                .limit(200)
            )
            return [
                {"run": RunRead.model_validate(run), "filename": source.filename}
                for _, run, source in rows
            ]

    async def start(self, owner, body):
        await self.recover(owner)
        request_hash = digest(body.model_dump(mode="json", exclude={"idempotency_key"}))
        async with self.sessions.begin() as session:
            await self.lock(session, owner)
            source = await self.source(session, owner, body.source_id)
            request = await session.get(RequestORM, (owner, body.idempotency_key))
            if request and request.request_hash != request_hash:
                raise ServiceError("IDEMPOTENCY_CONFLICT", "同一请求键不能用于不同请求", 409)
            old = await session.get(IngestORM, request.run_id) if request else None
            if old is None and not body.reprocess:
                old = await session.scalar(
                    select(IngestORM)
                    .where(IngestORM.owner == owner, IngestORM.source_id == body.source_id)
                    .order_by(IngestORM.created_at.desc())
                    .limit(1)
                )
            if old:
                run_id = old.run_id
                fresh = False
            else:
                if not self.extractor.ready:
                    raise ServiceError(
                        "MODEL_NOT_CONFIGURED", "请先配置模型 Provider、模型名及对应连接参数", 503
                    )
                snapshot = await self.config(owner, session)
                snapshot["model"] = getattr(self.extractor, "model", "test-provider")
                run = RunORM(
                    run_id=uuid4(),
                    workflow_type="ingest",
                    status="running",
                    stage="extracting",
                    version=1,
                    started_at=utc_now(),
                )
                session.add(run)
                await session.flush()
                run_id = run.run_id
                run.result_ref = f"/api/v1/ingests/{run_id}"
                session.add(
                    IngestORM(
                        run_id=run_id,
                        owner=owner,
                        source_id=source.id,
                        idempotency_key=body.idempotency_key,
                        request_hash=request_hash,
                        config=snapshot,
                    )
                )
                fresh = True
            if request is None:
                session.add(
                    RequestORM(
                        owner=owner,
                        key=body.idempotency_key,
                        request_hash=request_hash,
                        run_id=run_id,
                    )
                )
        if fresh:
            with log_context(run_id=str(run_id), workflow="ingest"):
                try:
                    async with asyncio.timeout(self.timeouts["execution_seconds"]):
                        await self._generate(owner, run_id)
                except asyncio.CancelledError:
                    await self.fail(
                        owner, run_id, "EXECUTION_INTERRUPTED", "请求执行中断，可重新生成计划"
                    )
                    raise
                except TimeoutError:
                    await self.fail(
                        owner, run_id, "INGEST_TIMEOUT", "知识提取流程超时，可重新生成计划"
                    )
                except Exception as exc:
                    logger.error("ingest_failed", exc_info=True)
                    code = exc.code if isinstance(exc, ServiceError) else "INGEST_FAILED"
                    message = (
                        exc.message
                        if isinstance(exc, ServiceError)
                        else "生成计划失败，请重试并通过请求ID检查日志"
                    )
                    await self.fail(owner, run_id, code, message)
        return await self.detail(owner, run_id)

    async def fail(self, owner, run_id, code, message):
        async with self.sessions.begin() as session:
            await self._owned(session, owner, run_id, True)
            run = await session.get(RunORM, run_id)
            if run.status == "running":
                change_state(run, "failed", "generation_failed", {"code": code, "message": message})

    async def _generate(self, owner, run_id):
        async with self.sessions() as session:
            row = await self._owned(session, owner, run_id)
            source = await self.source(session, owner, row.source_id)
            raw = await asyncio.to_thread(self.raw.read, owner, source.sha256)
            source_text = raw.decode("utf-8-sig")
            existing = list(
                await session.scalars(select(DefinitionORM).where(DefinitionORM.owner == owner))
            )
            snapshot = row.config
        # Bounded lexical discovery; the full catalog is used only for deterministic checks.
        words = source_text.casefold()
        relevant = sorted(
            existing,
            key=lambda d: (d.data["name"].casefold() in words, d.key in words),
            reverse=True,
        )[:30]
        context = [
            {
                "id": str(d.id),
                "key": d.key,
                "name": d.data["name"],
                "kind": d.data["kind"],
                "scope": d.data["scope"],
                "definition": d.data["definition"][:1000],
            }
            for d in relevant
        ]
        extraction = await self.extractor.extract(source_text, snapshot["body"], context)
        lint = check_candidates(extraction, source_text, snapshot["body"], existing)
        by_id = {d.id: d for d in existing}
        changes = []
        for c in extraction.candidates:
            before = by_id.get(c.target_id)
            data = c.model_dump(mode="json", exclude={"target_id", "reason"})
            data.update(source_id=str(source.id), source_hash=source.sha256)
            action = "UPDATE" if before else "CREATE"
            if before and before.data == data:
                action = "NO_CHANGE"
            changes.append(
                {
                    "action": action,
                    "definition_id": str(before.id if before else uuid4()),
                    "expected_version": before.version if before else 0,
                    "before": before.data if before else None,
                    "after": data,
                    "reason": c.reason,
                }
            )
        plan = {
            "version": 1,
            "source_id": str(source.id),
            "source_hash": source.sha256,
            "schema_version": "ontology-v1",
            "created_at": utc_now().isoformat(),
            "changes": changes,
            "lint": lint,
            "notes": extraction.notes,
            "extraction": extraction.model_dump(mode="json"),
        }
        async with self.sessions.begin() as session:
            row = await self._owned(session, owner, run_id, True)
            run = await session.get(RunORM, run_id)
            if run.status != "running":
                return
            row.plan, row.plan_hash = plan, digest(plan)
            if lint["errors"]:
                change_state(
                    run,
                    "failed",
                    "plan_validation_failed",
                    {
                        "code": "PLAN_INVALID",
                        "message": "候选计划未通过校验；请查看问题并调整配置后重新生成",
                    },
                )
            elif not changes or all(c["action"] == "NO_CHANGE" for c in changes):
                change_state(run, "succeeded", "no_change")
            else:
                change_state(run, "awaiting_approval", "review")
        logger.info("ingest_plan_generated", extra={"stage": "review"})

    async def decide(self, owner, run_id, body, approve):
        try:
            return await self._decide(owner, run_id, body, approve)
        except Exception as exc:
            # Publication transaction has rolled back. Persist a separate failed-attempt record.
            if approve:
                async with self.sessions.begin() as session:
                    row = await self._owned(session, owner, run_id, True)
                    if row.decision is None:
                        row.publication_errors = [
                            *row.publication_errors,
                            {
                                "at": utc_now().isoformat(),
                                "code": exc.code
                                if isinstance(exc, ServiceError)
                                else "PUBLICATION_FAILED",
                                "message": exc.message
                                if isinstance(exc, ServiceError)
                                else "发布事务失败，已回滚",
                                "plan_hash": body.plan_hash,
                            },
                        ][-20:]
            raise

    async def _decide(self, owner, run_id, body, approve):
        async with self.sessions.begin() as session:
            await self.lock(session, owner)
            row = await self._owned(session, owner, run_id, True)
            run = await session.get(RunORM, run_id)
            plan = row.plan
            if (
                not plan
                or row.plan_hash != body.plan_hash
                or plan["version"] != body.plan_version
                or digest(plan) != row.plan_hash
            ):
                raise ServiceError("PLAN_VERSION_CONFLICT", "计划版本不匹配，请重新查看", 409)
            if row.decision:
                if row.decision["action"] != ("approve" if approve else "reject"):
                    raise ServiceError("ALREADY_DECIDED", "计划已经处理", 409)
            else:
                if run.status != "awaiting_approval":
                    raise ServiceError("INVALID_RUN_STATE", "任务不处于待审批状态", 409)
                if approve:
                    await self._publish(session, owner, row, plan)
                    change_state(run, "succeeded", "published")
                else:
                    change_state(run, "cancelled", "rejected")
                row.decision = {
                    "action": "approve" if approve else "reject",
                    "actor": owner,
                    "at": utc_now().isoformat(),
                    "plan_hash": row.plan_hash,
                    "reason": getattr(body, "reason", ""),
                }
        return await self.detail(owner, run_id)

    async def _publish(self, session, owner, row, plan):
        source = await self.source(session, owner, row.source_id)
        raw = await asyncio.to_thread(self.raw.read, owner, source.sha256)
        if source.sha256 != plan["source_hash"]:
            raise ServiceError("SOURCE_CHANGED", "来源版本变化，必须重新生成计划", 409)
        existing = list(
            await session.scalars(select(DefinitionORM).where(DefinitionORM.owner == owner))
        )
        lint = check_candidates(
            Extraction.model_validate(plan["extraction"]),
            raw.decode("utf-8-sig"),
            row.config["body"],
            existing,
        )
        if lint["errors"]:
            raise ServiceError("PLAN_STALE", "计划已冲突或校验失败，请重新生成", 409)
        by_id = {str(d.id): d for d in existing}
        for c in plan["changes"]:
            current = by_id.get(c["definition_id"])
            if (current.version if current else 0) != c["expected_version"]:
                raise ServiceError("PLAN_STALE", "目标定义已变化，请重新生成计划", 409)
        for c in plan["changes"]:
            if c["action"] == "NO_CHANGE":
                continue
            current = by_id.get(c["definition_id"])
            if current is None:
                current = DefinitionORM(
                    id=UUID(c["definition_id"]), owner=owner, key=c["after"]["key"], version=0
                )
                session.add(current)
            current.version += 1
            current.data = c["after"]
            current.markdown = render_markdown(c["after"])
            current.updated_at = utc_now()
            await session.flush()
            session.add(
                RevisionORM(
                    definition_id=current.id,
                    run_id=row.run_id,
                    version=current.version,
                    data=current.data,
                    markdown=current.markdown,
                )
            )
        await session.flush()
        # All definitions, journal entries, decision and final run state commit together.
        # Failure at any point rolls back the whole publication; Raw and plan remain available.
        await self.verify_publication(session, owner, plan)

    async def verify_publication(self, session, owner, plan):
        for c in plan["changes"]:
            saved = await session.get(DefinitionORM, UUID(c["definition_id"]))
            if saved is not None:
                await session.refresh(saved)
            if saved is None or saved.owner != owner or saved.data != c["after"]:
                raise ServiceError("PUBLICATION_INVALID", "写入后校验失败，发布已回滚", 409)

    async def definitions(self, owner):
        async with self.sessions() as session:
            rows = await session.scalars(
                select(DefinitionORM)
                .where(DefinitionORM.owner == owner)
                .order_by(DefinitionORM.updated_at.desc())
                .limit(200)
            )
            return [definition_view(r) for r in rows]

    async def definition(self, owner, definition_id):
        async with self.sessions() as session:
            row = await session.get(DefinitionORM, definition_id)
            if row is None or row.owner != owner:
                raise ServiceError("DEFINITION_NOT_FOUND", "定义不存在", 404)
            revisions = await session.scalars(
                select(RevisionORM)
                .where(RevisionORM.definition_id == definition_id)
                .order_by(RevisionORM.version.desc())
            )
            return {
                **definition_view(row),
                "revisions": [
                    {
                        "version": r.version,
                        "run_id": str(r.run_id),
                        "data": r.data,
                        "markdown": r.markdown,
                    }
                    for r in revisions
                ],
            }
