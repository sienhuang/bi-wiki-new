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
async def database():
    runtime = get_settings()
    # 所有 DDL 前校验，测试只操作独立测试库内本次随机 schema。
    url = checked_test_url(runtime)
    schema = f"test_{uuid4().hex}"
    config = runtime.model_copy(update={"database_url": SecretStr(url), "database_schema": schema})
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
