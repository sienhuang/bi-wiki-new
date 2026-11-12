"""Real PostgreSQL workflow tests; extractor is explicitly a fake model."""

import asyncio
import base64
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from bi_wiki.api.deps import get_principal
from bi_wiki.core.errors import ServiceError
from bi_wiki.db.models import RunORM, utc_now
from bi_wiki.ingest.models import Extraction
from bi_wiki.ingest.tables import DefinitionORM, RevisionORM
from bi_wiki.services.auth import Principal

RAW = "DAU 是每日登录的去重游戏账号数，排除测试账号。\n时区尚未明确。\n"


def sample(key="dau", target_id=None):
    return {
        "key": key,
        "kind": "metric",
        "name": "DAU",
        "definition": "每日登录的去重游戏账号数，排除测试账号。",
        "scope": "游戏",
        "attributes": {"粒度": "日"},
        "unknowns": ["时区未明确"],
        "evidence": [{"start_line": 1, "end_line": 1, "quote": RAW.splitlines()[0]}],
        "relations": [],
        "reason": "来源明确描述了DAU",
        "target_id": target_id,
    }


class FakeExtractor:
    ready = True

    def __init__(self, candidates=None):
        self.candidates = candidates if candidates is not None else [sample()]
        self.calls = 0

    async def extract(self, text, config, existing):
        self.calls += 1
        return Extraction.model_validate({"candidates": self.candidates})


async def upload(client, filename="dau.md", raw=None):
    connection, app = client
    raw = RAW.encode() if raw is None else raw
    response = await connection.post(
        "/api/v1/sources",
        json={"filename": filename, "content_base64": base64.b64encode(raw).decode()},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["source"]


async def start(client, source, **extra):
    connection, _ = client
    response = await connection.post(
        "/api/v1/ingests",
        json={"source_id": source["id"], "idempotency_key": str(uuid4()), **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def approval(detail):
    return {"plan_version": detail["plan"]["version"], "plan_hash": detail["plan_hash"]}


async def test_complete_approval_and_duplicate_delivery(client):
    connection, app = client
    app.state.ingest.extractor = fake = FakeExtractor()
    source = await upload(client)
    again = await upload(client)
    assert source["id"] == again["id"]
    raw = app.state.ingest.raw.read("test-user", source["sha256"])
    assert raw == RAW.encode()
    first = await start(client, source)
    duplicate = await start(client, source)
    assert first["run"]["run_id"] == duplicate["run"]["run_id"]
    assert fake.calls == 1
    assert first["run"]["status"] == "awaiting_approval"
    assert (await connection.get("/api/v1/definitions")).json()["data"] == []
    path = "/api/v1/runs/" + first["run"]["run_id"] + "/approve"
    published = await connection.post(path, json=approval(first))
    assert published.status_code == 200, published.text
    assert published.json()["data"]["run"]["stage"] == "published"
    assert (await connection.post(path, json=approval(first))).status_code == 200
    definitions = (await connection.get("/api/v1/definitions")).json()["data"]
    assert len(definitions) == 1
    detail = (await connection.get("/api/v1/definitions/" + definitions[0]["id"])).json()["data"]
    assert len(detail["revisions"]) == 1
    assert detail["data"]["source_hash"] == source["sha256"]
    assert "时区未明确" in detail["markdown"]


async def test_bad_evidence_never_reaches_approval(client):
    connection, app = client
    candidate = sample()
    candidate["evidence"][0]["quote"] = "invented"
    app.state.ingest.extractor = FakeExtractor([candidate])
    result = await start(client, await upload(client))
    assert result["run"]["status"] == "failed"
    assert result["plan"]["lint"]["status"] == "FAIL"
    assert (
        await connection.post(
            "/api/v1/runs/" + result["run"]["run_id"] + "/approve", json=approval(result)
        )
    ).status_code == 409
    assert (await connection.get("/api/v1/definitions")).json()["data"] == []


async def test_owner_isolation_including_generic_run_route(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    source = await upload(client)
    result = await start(client, source)
    app.dependency_overrides[get_principal] = lambda: Principal(uid="other")
    for path in [
        "/api/v1/sources/" + source["id"],
        "/api/v1/ingests/" + result["run"]["run_id"],
        "/api/v1/runs/" + result["run"]["run_id"],
    ]:
        assert (await connection.get(path)).status_code == 404
    assert (await connection.get("/api/v1/sources")).json()["data"] == []
    assert (
        await connection.post(
            "/api/v1/runs/" + result["run"]["run_id"] + "/approve", json=approval(result)
        )
    ).status_code == 404


async def test_source_changed_blocks_publish(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    source = await upload(client)
    result = await start(client, source)
    app.state.ingest.raw.path("test-user", source["sha256"]).write_bytes(b"changed")
    response = await connection.post(
        "/api/v1/runs/" + result["run"]["run_id"] + "/approve", json=approval(result)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_CHANGED"
    assert (await connection.get("/api/v1/definitions")).json()["data"] == []


async def test_competing_plans_and_version_binding(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    source = await upload(client)
    a = await start(client, source)
    b = await start(client, source, reprocess=True)
    path = "/api/v1/runs/" + a["run"]["run_id"] + "/approve"
    assert (await connection.post(path, json={**approval(a), "plan_version": 2})).status_code == 409
    assert (await connection.post(path, json=approval(a))).status_code == 200
    stale = await connection.post(
        "/api/v1/runs/" + b["run"]["run_id"] + "/approve", json=approval(b)
    )
    assert stale.status_code == 409
    assert (await connection.get("/api/v1/ingests/" + b["run"]["run_id"])).json()["data"]["run"][
        "status"
    ] == "awaiting_approval"


async def test_rejection_retains_source_and_blocks_publish(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    source = await upload(client)
    result = await start(client, source)
    base = "/api/v1/runs/" + result["run"]["run_id"]
    assert (
        await connection.post(base + "/reject", json={**approval(result), "reason": "需要补充时区"})
    ).status_code == 200
    assert (await connection.post(base + "/approve", json=approval(result))).status_code == 409
    assert (await connection.get("/api/v1/sources/" + source["id"])).status_code == 200


async def test_postwrite_failure_rolls_back_all_definitions_and_journal(client, monkeypatch):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor([sample(), sample("other_metric")])
    result = await start(client, await upload(client))

    async def broken(*args):
        raise ServiceError("PUBLICATION_INVALID", "写入后校验失败", 409)

    monkeypatch.setattr(app.state.ingest, "verify_publication", broken)
    assert (
        await connection.post(
            "/api/v1/runs/" + result["run"]["run_id"] + "/approve", json=approval(result)
        )
    ).status_code == 409
    async with app.state.database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DefinitionORM)) == 0
        assert await session.scalar(select(func.count()).select_from(RevisionORM)) == 0
    reread = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()["data"]
    assert reread["decision"] is None and reread["run"]["status"] == "awaiting_approval"


@pytest.mark.parametrize(
    ("filename", "raw", "status"),
    [
        ("bad.pdf", b"x", 415),
        ("../bad.md", b"x", 422),
        ("bad.txt", b"\xff", 422),
        ("empty.md", b" ", 413),
        ("large.md", b"x" * 131073, 413),
    ],
)
async def test_invalid_sources(client, filename, raw, status):
    connection, _ = client
    result = await connection.post(
        "/api/v1/sources",
        json={"filename": filename, "content_base64": base64.b64encode(raw).decode()},
    )
    assert result.status_code == status


async def test_model_unavailable_has_no_fake_plan(client):
    connection, _ = client
    source = await upload(client)
    result = await connection.post(
        "/api/v1/ingests", json={"source_id": source["id"], "idempotency_key": str(uuid4())}
    )
    assert result.status_code == 503
    assert result.json()["code"] == "MODEL_NOT_CONFIGURED"


async def test_config_snapshot_and_interruption_recovery(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    result = await start(client, await upload(client))
    config = (await connection.get("/api/v1/ingest-config")).json()["data"]
    config["body"]["instructions"] = "另一版本"
    assert (await connection.post("/api/v1/ingest-config", json=config["body"])).status_code == 201
    reread = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()["data"]
    assert reread["config"]["version"] == 0
    async with app.state.database.sessions.begin() as session:
        run = await session.get(RunORM, UUID(result["run"]["run_id"]))
        run.status, run.stage = "running", "extracting"
        run.updated_at = utc_now() - timedelta(minutes=8)
    recovered = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()["data"]
    assert recovered["run"]["status"] == "failed"
    assert recovered["run"]["error"]["code"] == "EXECUTION_INTERRUPTED"


async def test_idempotency_mismatch(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    a = await upload(client)
    b = await upload(client, raw=b"other source")
    key = str(uuid4())
    assert (
        await connection.post(
            "/api/v1/ingests", json={"source_id": a["id"], "idempotency_key": key}
        )
    ).status_code == 200
    assert (
        await connection.post(
            "/api/v1/ingests", json={"source_id": b["id"], "idempotency_key": key}
        )
    ).status_code == 409


async def test_concurrent_approvals_create_one_revision(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    result = await start(client, await upload(client))
    path = "/api/v1/runs/" + result["run"]["run_id"] + "/approve"
    responses = await asyncio.gather(
        *[connection.post(path, json=approval(result)) for _ in range(2)]
    )
    assert [r.status_code for r in responses] == [200, 200]
    async with app.state.database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(RevisionORM)) == 1


async def test_update_history_and_stale_update(client):
    connection, app = client
    fake = FakeExtractor()
    app.state.ingest.extractor = fake
    source = await upload(client)
    first = await start(client, source)
    await connection.post(
        "/api/v1/runs/" + first["run"]["run_id"] + "/approve", json=approval(first)
    )
    definitions = (await connection.get("/api/v1/definitions")).json()["data"]
    target = definitions[0]["id"]
    candidate = sample(target_id=target)
    candidate["unknowns"] = ["需要业务方确认时区"]
    fake.candidates = [candidate]
    a = await start(client, source, reprocess=True)
    b = await start(client, source, reprocess=True)
    assert a["plan"]["changes"][0]["action"] == "UPDATE"
    assert a["plan"]["changes"][0]["expected_version"] == 1
    assert (
        await connection.post("/api/v1/runs/" + a["run"]["run_id"] + "/approve", json=approval(a))
    ).status_code == 200
    assert (
        await connection.post("/api/v1/runs/" + b["run"]["run_id"] + "/approve", json=approval(b))
    ).status_code == 409
    detail = (await connection.get("/api/v1/definitions/" + target)).json()["data"]
    assert detail["version"] == 2
    assert [r["version"] for r in detail["revisions"]] == [2, 1]
    history = (await connection.get("/api/v1/ingests")).json()["data"]
    assert len(history) == 3


async def test_duplicate_request_alias_is_stable_after_reprocessing(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    source = await upload(client)
    first = await start(client, source)
    key = str(uuid4())
    body = {"source_id": source["id"], "idempotency_key": key}
    alias = (await connection.post("/api/v1/ingests", json=body)).json()["data"]
    await start(client, source, reprocess=True)
    repeat = (await connection.post("/api/v1/ingests", json=body)).json()["data"]
    assert alias["run"]["run_id"] == first["run"]["run_id"] == repeat["run"]["run_id"]


async def test_invalid_relation_and_model_failure_are_not_success(client):
    _, app = client
    candidate = sample()
    candidate["relations"] = [
        {"type": "measures", "target_key": "missing", "evidence": candidate["evidence"][0]}
    ]
    fake = FakeExtractor([candidate])
    app.state.ingest.extractor = fake
    source = await upload(client)
    result = await start(client, source)
    assert result["run"]["status"] == "failed"

    async def unavailable(*args):
        raise ServiceError("MODEL_UNAVAILABLE", "模型暂时不可用", 503)

    fake.extract = unavailable
    failure = await start(client, source, reprocess=True)
    assert failure["run"]["status"] == "failed"
    assert failure["run"]["error"]["code"] == "MODEL_UNAVAILABLE"
    assert failure["plan"] is None


async def test_raw_symlink_rejected_and_request_size_bounded(client, tmp_path):
    connection, app = client
    source = await upload(client)
    path = app.state.ingest.raw.path("test-user", source["sha256"])
    other = tmp_path / "outside.txt"
    other.write_bytes(RAW.encode())
    path.unlink()
    path.symlink_to(other)
    assert (await connection.get("/api/v1/sources/" + source["id"])).status_code == 409
    result = await connection.post("/api/v1/sources", content=b"x" * 200001)
    assert result.status_code == 413


async def test_published_knowledge_survives_application_restart(database):
    import httpx

    from bi_wiki.main import create_app

    config, _ = database
    first = create_app(config)
    first.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")
    async with first.router.lifespan_context(first):
        first.state.ingest.extractor = FakeExtractor()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first), base_url="http://test"
        ) as connection:
            client = (connection, first)
            result = await start(client, await upload(client))
            assert (
                await connection.post(
                    "/api/v1/runs/" + result["run"]["run_id"] + "/approve", json=approval(result)
                )
            ).status_code == 200
    second = create_app(config)
    second.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")
    async with second.router.lifespan_context(second):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second), base_url="http://test"
        ) as connection:
            definitions = (await connection.get("/api/v1/definitions")).json()["data"]
            assert len(definitions) == 1
            assert definitions[0]["data"]["key"] == "dau"
            run = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()[
                "data"
            ]
            assert run["decision"]["action"] == "approve"
            assert (await connection.get("/api/v1/sources/" + result["source"]["id"])).json()[
                "data"
            ]["text"] == RAW


async def test_provider_failure_is_persisted_without_plan(client):
    import httpx

    from bi_wiki.ingest.extractor import Extractor
    from bi_wiki.llm.openai_compat import ModelConfig, OpenAICompatibleProvider

    connection, app = client
    provider = OpenAICompatibleProvider(
        ModelConfig("https://model.example/v1", "test"),
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text="private-detail")),
    )
    app.state.ingest.extractor = Extractor(provider)
    result = await start(client, await upload(client))
    assert result["run"]["status"] == "failed"
    assert result["run"]["error"]["code"] == "MODEL_ACCESS_DENIED"
    assert result["plan"] is None
    reread = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()["data"]
    assert reread["run"]["error"] == result["run"]["error"]
    assert "private-detail" not in str(reread)


async def test_timeout_policy_and_request_lookup(client):
    connection, app = client
    app.state.ingest.extractor = FakeExtractor()
    config = (await connection.get("/api/v1/ingest-config")).json()["data"]
    assert config["timeouts"]["execution_seconds"] == config["timeouts"]["model_seconds"] + 30
    key = str(uuid4())
    source = await upload(client)
    result = (
        await connection.post(
            "/api/v1/ingests",
            json={
                "source_id": source["id"],
                "idempotency_key": key,
            },
        )
    ).json()["data"]
    lookup = await connection.get("/api/v1/ingest-requests/" + key)
    assert lookup.json()["data"]["run"]["run_id"] == result["run"]["run_id"]
    assert (await connection.get("/api/v1/ingest-requests/" + str(uuid4()))).status_code == 404
    async with app.state.database.sessions.begin() as session:
        run = await session.get(RunORM, UUID(result["run"]["run_id"]))
        run.status, run.stage = "running", "extracting"
        run.updated_at = utc_now() - timedelta(minutes=4)
    # Old 3-minute rule must not interrupt a task within its captured deadline.
    reread = (await connection.get("/api/v1/ingests/" + result["run"]["run_id"])).json()["data"]
    assert reread["run"]["status"] == "running"
