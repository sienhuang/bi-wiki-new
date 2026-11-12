import asyncio
import contextlib
import signal
import tempfile
from pathlib import Path
from uuid import uuid4

import uvicorn
from pydantic import SecretStr
from sqlalchemy.schema import CreateSchema, DropSchema
from test_ingest import FakeExtractor

from bi_wiki.api.deps import get_auth_provider, get_principal
from bi_wiki.core.config import checked_test_url, get_settings
from bi_wiki.db.database import Database
from bi_wiki.ingest.api import get_ingest
from bi_wiki.ingest.raw import RawStore
from bi_wiki.ingest.service import IngestService
from bi_wiki.main import create_app
from bi_wiki.services.auth import AuthSession, Principal


async def main():
    runtime = get_settings()
    schema = "test_" + uuid4().hex
    print("ISOLATED_TEST_SCHEMA=" + schema, flush=True)
    with tempfile.TemporaryDirectory(prefix="biwiki-e2e-") as temp:
        config = runtime.model_copy(
            update={
                "database_url": SecretStr(checked_test_url(runtime)),
                "database_schema": schema,
                "raw_root": (await asyncio.to_thread(Path(temp).resolve)) / "raw",
            }
        )
        db = Database(config)
        try:
            async with db.engine.begin() as c:
                await c.execute(CreateSchema(schema))
            app = create_app(config)
            identity = Principal(uid="isolated-browser-test", name="验收测试用户")

            class Auth:
                async def refresh(self, token):
                    return AuthSession(token="fake-test-token", user=identity)

            app.dependency_overrides[get_principal] = lambda: identity
            app.dependency_overrides[get_auth_provider] = Auth
            app.dependency_overrides[get_ingest] = lambda: IngestService(
                db.sessions, RawStore(config.raw_root), FakeExtractor()
            )
            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=8029, log_level="warning")
            )
            server.capture_signals = contextlib.nullcontext
            for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
                asyncio.get_running_loop().add_signal_handler(
                    shutdown_signal, lambda: setattr(server, "should_exit", True)
                )
            await server.serve()
        finally:
            async with db.engine.begin() as c:
                await c.execute(DropSchema(schema, cascade=True, if_exists=True))
            await db.close()
            print("ISOLATED_SCHEMA_AND_RAW_REMOVED", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
