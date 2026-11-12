from uuid import uuid4

import httpx
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.schema import CreateSchema, DropSchema

from bi_wiki.api.deps import get_principal
from bi_wiki.core.config import checked_test_url, get_settings
from bi_wiki.db.database import Database
from bi_wiki.main import create_app
from bi_wiki.services.auth import Principal


@pytest_asyncio.fixture
async def database(tmp_path):
    runtime = get_settings()
    # 所有 DDL 前校验，测试只操作独立测试库内本次随机 schema。
    url = checked_test_url(runtime)
    schema = f"test_{uuid4().hex}"
    config = runtime.model_copy(
        update={
            "database_url": SecretStr(url),
            "database_schema": schema,
            "raw_root": tmp_path / "raw",
            "raw_backend": "local",
            "llm_provider": "openai",
            "llm_timeout_seconds": 300,
            "ingest_overhead_seconds": 30,
            "ingest_recovery_grace_seconds": 60,
            "llm_cli_command": [],
            "llm_base_url": "",
            "llm_model": "",
            "llm_api_key": None,
        }
    )
    db = Database(config)
    try:
        async with db.engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        await db.initialize()
        yield config, db
    finally:
        async with db.engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        await db.close()


@pytest_asyncio.fixture
async def client(database):
    config, _ = database
    application = create_app(config)
    application.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://testserver"
        ) as connection:
            yield connection, application
