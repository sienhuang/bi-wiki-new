"""Contract checks across success, auth, validation and unexpected failure paths."""

import httpx
import pytest

from bi_wiki.api.deps import get_auth_provider, get_principal
from bi_wiki.main import create_app
from bi_wiki.services.auth import AuthSession, Principal


def assert_envelope(response, status):
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"code", "message", "data", "request_id", "details"}
    assert body["request_id"] == response.headers["x-request-id"]
    assert isinstance(body["message"], str) and isinstance(body["details"], list)
    if status < 400:
        assert body["code"] == "OK" and body["data"] is not None
    else:
        assert body["code"] != "OK" and body["data"] is None
    return body


async def test_success_contract_for_health_auth_and_runs(client):
    connection, app = client

    class AuthStub:
        async def refresh(self, token):
            return AuthSession(token="fake-token", user=Principal(uid="test"))

    app.dependency_overrides[get_auth_provider] = AuthStub
    try:
        for path in ["/health", "/api/v1/auth/config", "/api/v1/auth/me"]:
            assert_envelope(await connection.get(path), 200)
        session = await connection.post("/api/v1/auth/session", headers={"X-MOA-Token": "fake"})
        assert_envelope(session, 200)
        assert session.headers["cache-control"] == "no-store"
        created = await connection.post("/api/v1/runs", json={"workflow_type": "query"})
        body = assert_envelope(created, 201)
        read = assert_envelope(await connection.get(created.headers["Location"]), 200)
        assert read["data"] == body["data"]
        assert read["request_id"] != body["request_id"]
    finally:
        app.dependency_overrides.pop(get_auth_provider)


@pytest.mark.parametrize(
    ("method", "path", "payload", "status"),
    [
        ("GET", "/unknown", None, 404),
        ("GET", "/api/v1/runs/00000000-0000-0000-0000-000000000001", None, 404),
        ("POST", "/api/v1/runs", {"workflow_type": "invalid"}, 422),
        ("POST", "/api/v1/queries", {"question": "test"}, 501),
        ("POST", "/health", None, 405),
    ],
)
async def test_error_contract(client, method, path, payload, status):
    connection, _ = client
    response = await connection.request(method, path, json=payload)
    assert_envelope(response, status)
    if status == 405:
        assert response.headers["allow"] == "GET"


async def test_missing_auth_contract(client):
    connection, app = client
    app.dependency_overrides.pop(get_principal)
    result = assert_envelope(await connection.get("/api/v1/auth/me"), 401)
    assert result["code"] == "AUTH_TOKEN_MISSING"


async def test_unhandled_error_contract_does_not_leak_values():
    app = create_app()

    @app.get("/failure")
    async def failure():
        raise RuntimeError("private-exception-value")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/failure")
    assert_envelope(response, 500)
    assert "private-exception-value" not in response.text
