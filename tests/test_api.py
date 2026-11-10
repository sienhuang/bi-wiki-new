from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import DropTable

from bi_wiki.api.deps import get_database, get_principal, get_run_repository
from bi_wiki.db.models import RunORM
from bi_wiki.main import create_app
from bi_wiki.services.auth import Principal


async def test_health_and_task_registration(client):
    connection, _ = client
    health = await connection.get("/health")
    assert health.status_code == 200
    assert health.json()["data"]["database"] == "ok"
    response = await connection.post("/api/v1/runs", json={"workflow_type": "query"})
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "queued"
    read = await connection.get(response.headers["Location"])
    assert read.json()["data"] == response.json()["data"]
    assert response.headers["X-Request-ID"]


async def test_not_found_and_validation_do_not_echo_input(client):
    connection, _ = client
    response = await connection.get(f"/api/v1/runs/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"
    response = await connection.post(
        "/api/v1/runs", json={"workflow_type": "secret-input", "status": "succeeded"}
    )
    assert response.status_code == 422
    assert "secret-input" not in response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await connection.get("/api/v1/runs/not-a-uuid")).status_code == 422
    assert (await connection.patch(f"/api/v1/runs/{uuid4()}", json={})).status_code == 405


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/ingests", {"source_ref": "inbox/example.md"}),
        ("/api/v1/queries", {"question": "什么是日活？"}),
        ("/api/v1/lints", {}),
        (f"/api/v1/runs/{uuid4()}/approve", {"plan_version": 1}),
        (f"/api/v1/runs/{uuid4()}/cancel", {}),
    ],
)
async def test_reserved_endpoints_report_not_implemented_without_records(client, path, body):
    connection, application = client
    async with application.state.database.sessions() as session:
        before = await session.scalar(select(func.count()).select_from(RunORM))
    response = await connection.post(path, json=body)
    assert response.status_code == 501
    assert response.json()["code"] == "FEATURE_NOT_IMPLEMENTED"
    async with application.state.database.sessions() as session:
        after = await session.scalar(select(func.count()).select_from(RunORM))
    assert before == after


async def test_empty_question_is_invalid(client):
    connection, _ = client
    assert (await connection.post("/api/v1/queries", json={"question": "  "})).status_code == 422


async def test_database_failure_is_503_without_secret(client):
    connection, application = client

    class FailingDatabase:
        async def check(self):
            raise OperationalError("sensitive-sql", {}, Exception("private-password"))

    application.dependency_overrides[get_database] = FailingDatabase
    try:
        response = await connection.get("/health")
        assert response.status_code == 503
        assert response.json()["code"] == "DATABASE_UNAVAILABLE"
        assert "private-password" not in response.text and "sensitive-sql" not in response.text
    finally:
        application.dependency_overrides.pop(get_database)
    assert (await connection.get("/health")).status_code == 200


async def test_run_routes_support_repository_override(client):
    connection, application = client
    calls = []
    actual = application.state.runs

    class RecordingRepository:
        async def create(self, workflow_type):
            calls.append("create")
            return await actual.create(workflow_type)

        async def get(self, run_id):
            calls.append("get")
            return await actual.get(run_id)

    application.dependency_overrides[get_run_repository] = RecordingRepository
    try:
        created = await connection.post("/api/v1/runs", json={"workflow_type": "query"})
        assert created.status_code == 201
        read = await connection.get(created.headers["Location"])
        assert read.json()["data"] == created.json()["data"]
        assert calls == ["create", "get"]
    finally:
        application.dependency_overrides.pop(get_run_repository)


async def test_startup_fails_when_database_schema_is_unavailable(database):
    config, db = database
    async with db.engine.begin() as connection:
        await connection.execute(DropTable(RunORM.__table__))
    application = create_app(config.model_copy(update={"initialize_database": False}))
    with pytest.raises(RuntimeError, match="DATABASE_UNAVAILABLE") as error:
        async with application.router.lifespan_context(application):
            pytest.fail("missing task table must prevent startup")
    assert config.database_url.get_secret_value() not in str(error.value)


async def test_openapi_describes_actual_error_and_reserved_contracts(client):
    connection, _ = client
    document = (await connection.get("/openapi.json")).json()
    assert "501" in document["paths"]["/api/v1/queries"]["post"]["responses"]
    assert "200" not in document["paths"]["/api/v1/queries"]["post"]["responses"]
    invalid = document["paths"]["/api/v1/runs"]["post"]["responses"]["422"]
    assert invalid["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ApiResponse_NoneType_"
    )


async def test_tasks_survive_application_and_connection_restart(database):
    config, _ = database
    first = create_app(config)
    first.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")
    async with first.router.lifespan_context(first):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first), base_url="http://testserver"
        ) as connection:
            created = await connection.post("/api/v1/runs", json={"workflow_type": "ingest"})
            run_id = created.json()["data"]["run_id"]
    second = create_app(config)
    second.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")
    async with second.router.lifespan_context(second):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second), base_url="http://testserver"
        ) as connection:
            read = await connection.get(f"/api/v1/runs/{run_id}")
            assert read.status_code == 200
            assert read.json()["data"] == created.json()["data"]


async def test_knowledge_directory_is_untouched(database, tmp_path):
    config, _ = database
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    source = knowledge / "example.md"
    source.write_bytes(b"original bytes\n")
    before = {
        str(p.relative_to(knowledge)): p.read_bytes() for p in knowledge.rglob("*") if p.is_file()
    }
    application = create_app(config.model_copy(update={"knowledge_root": knowledge}))
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://testserver"
        ) as connection:
            await connection.get("/health")
            await connection.post("/api/v1/ingests", json={"source_ref": "example.md"})
            await connection.post("/api/v1/queries", json={"question": "read example"})
    after = {
        str(p.relative_to(knowledge)): p.read_bytes() for p in knowledge.rglob("*") if p.is_file()
    }
    assert before == after
