import asyncio
import json
import logging
import sys

import httpx
import pytest

from bi_wiki.api.deps import get_principal
from bi_wiki.core.logging import JsonFormatter, log_context, logger, setup_logging, timed_step
from bi_wiki.main import create_app
from bi_wiki.services.auth import Principal


def record():
    return logging.LogRecord("bi_wiki", logging.INFO, __file__, 1, "probe", (), None)


async def test_context_isolation_and_restoration():
    async def worker(value):
        with log_context(request_id=value):
            await asyncio.sleep(0)
            with log_context(run_id="run"):
                assert json.loads(JsonFormatter().format(record()))["run_id"] == "run"
            result = json.loads(JsonFormatter().format(record()))
            assert "run_id" not in result
            return result["request_id"]

    assert await asyncio.gather(worker("a"), worker("b")) == ["a", "b"]
    assert "request_id" not in json.loads(JsonFormatter().format(record()))


def test_exception_diagnostics_exclude_values():
    try:
        raise ValueError("private-body postgresql://user:password@host/db")
    except ValueError:
        item = record()
        item.exc_info = sys.exc_info()
        result = JsonFormatter().format(item)
    assert "private-body" not in result and "password" not in result
    data = json.loads(result)
    assert data["error_type"] == "ValueError"
    assert data["stack"][-1]["function"] == "test_exception_diagnostics_exclude_values"


def test_third_party_messages_and_extra_are_not_exposed():
    item = logging.LogRecord(
        "httpx", logging.WARNING, __file__, 1, "GET %s", ("https://host/?token=private",), None
    )
    item.body = "private-body"
    data = JsonFormatter().format(item)
    assert "private" not in data
    assert json.loads(data)["logger"] == "httpx"


def test_file_rotation_and_idempotent_setup(tmp_path):
    path = tmp_path / "logs" / "service.jsonl"
    try:
        setup_logging("INFO", log_file=path, backup_count=2)
        setup_logging("INFO", log_file=path, backup_count=2)
        logger.info("only_once")
        logging.getLogger("uvicorn.error").warning("unsafe private-body")
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        assert [line["event"] for line in lines].count("only_once") == 1
        assert sum(line["logger"] == "uvicorn.error" for line in lines) == 1
        assert "private-body" not in path.read_text()
        handler = next(h for h in logging.getLogger().handlers if hasattr(h, "doRollover"))
        handler.doRollover()
        logger.info("after_rotation")
        assert json.loads(path.read_text())["event"] == "after_rotation"
        assert len(list(path.parent.glob("service.jsonl.*"))) == 1
    finally:
        setup_logging("INFO")


def test_step_failure_and_context_cleanup(caplog):
    with caplog.at_level(logging.INFO), pytest.raises(ValueError), timed_step("load"):
        raise ValueError("private")
    entry = next(r for r in caplog.records if r.msg == "step_completed")
    assert entry.status == "failed" and entry.elapsed_ms >= 0
    assert "stage" not in json.loads(JsonFormatter().format(record()))


async def test_request_run_correlation_and_error_completion(database, tmp_path):
    config, _ = database
    path = tmp_path / "requests.jsonl"
    config = config.model_copy(update={"log_file": path})
    app = create_app(config)
    app.dependency_overrides[get_principal] = lambda: Principal(uid="test-user")

    @app.get("/explode")
    async def explode():
        logger.info("before_failure")
        raise ValueError("sensitive-body")

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/runs", json={"workflow_type": "query"})
            assert response.status_code == 201
            failure = await client.get("/explode?token=hidden")
            assert failure.status_code == 500
            health = await client.get("/health")
            assert health.status_code == 200
    setup_logging("INFO")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    registered = next(x for x in lines if x["event"] == "run_registered")
    assert registered["request_id"] == response.headers["x-request-id"]
    assert registered["run_id"] == response.json()["data"]["run_id"]
    errors = [x for x in lines if x["event"] == "request_failed"]
    assert len(errors) == 1 and errors[0]["stack"]
    assert errors[0]["request_id"] == failure.headers["x-request-id"]
    completed = [x for x in lines if x["event"] == "http_request"]
    assert len(completed) == 3
    assert next(x for x in completed if x["route"] == "/explode")["status_code"] == 500
    assert len({x["request_id"] for x in completed}) == 3
    assert "sensitive-body" not in path.read_text() and "hidden" not in path.read_text()
