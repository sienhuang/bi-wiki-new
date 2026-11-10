"""MOA contract tests use HTTP mocks; no real account or credentials."""

import httpx
import pytest

from bi_wiki.api.deps import get_auth_provider, get_principal
from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.services.auth import MoaAuthProvider


def config():
    return Settings(_env_file=None, database_url="postgresql://test@localhost/unused")


def identity(**updates):
    return {"uid": 123, "name": "测试用户", "nick": "test-user", "project": 1564, **updates}


async def test_refresh_validates_identity_and_replacement():
    calls = []

    def handler(request):
        calls.append((request.url.host, request.url.path, request.content))
        result = (
            {"token": "replacement", "project": 1564}
            if request.url.path == "/api/refresh"
            else identity()
        )
        return httpx.Response(200, json={"code": 0, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await MoaAuthProvider(config(), client).refresh("original")
    assert result.user.uid == "123" and result.token == "replacement"
    assert [item[1] for item in calls] == ["/api/getinfo", "/api/refresh", "/api/getinfo"]
    assert b"replacement" in calls[-1][2]


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"code": 1}, 401),
        ({"code": 0, "result": identity(project=999)}, 403),
        ({"code": 0, "result": identity(uid=None)}, 503),
        ({"code": 0, "result": identity(uid=True)}, 503),
        ({"code": 0, "result": []}, 503),
        ([], 503),
        ({"code": False, "result": identity()}, 503),
    ],
)
async def test_invalid_auth_results_fail_closed(payload, status):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ServiceError) as error:
            await MoaAuthProvider(config(), client).authenticate("test-token")
        assert error.value.status_code == status


@pytest.mark.parametrize("mode", ["timeout", "bad_json", "server_error"])
async def test_upstream_failure_is_sanitized(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private-token")
        if mode == "bad_json":
            return httpx.Response(200, text="private-token")
        return httpx.Response(500, text="private-token")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ServiceError) as error:
            await MoaAuthProvider(config(), client).authenticate("test-token")
        assert error.value.status_code == 503
        assert "private-token" not in str(error.value)


async def test_identity_cannot_change_during_refresh():
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        result = {"token": "replacement", "project": 1564} if count == 2 else identity(uid=count)
        return httpx.Response(200, json={"code": 0, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ServiceError) as error:
            await MoaAuthProvider(config(), client).refresh("test-token")
        assert error.value.status_code == 401


async def test_api_auth_gate_and_server_identity(client):
    connection, app = client
    app.dependency_overrides.pop(get_principal)

    def handler(request):
        result = (
            {"token": "renewed", "project": 1564}
            if request.url.path == "/api/refresh"
            else identity()
        )
        return httpx.Response(200, json={"code": 0, "result": result})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app.dependency_overrides[get_auth_provider] = lambda: MoaAuthProvider(config(), upstream)
        try:
            assert (await connection.get("/health")).status_code == 200
            assert (await connection.get("/api/v1/auth/config")).json()["data"][
                "project_id"
            ] == 1564
            for method, path in [
                ("POST", "/api/v1/runs"),
                ("GET", "/api/v1/runs/00000000-0000-0000-0000-000000000001"),
                ("POST", "/api/v1/queries"),
                ("POST", "/api/v1/ingests"),
                ("POST", "/api/v1/lints"),
                ("POST", "/api/v1/runs/00000000-0000-0000-0000-000000000001/approve"),
                ("POST", "/api/v1/runs/00000000-0000-0000-0000-000000000001/cancel"),
            ]:
                response = await connection.request(method, path, json={})
                assert response.status_code == 401
                assert response.json()["code"] == "AUTH_TOKEN_MISSING"
            headers = {
                "X-MOA-Token": "valid-token",
                "X-MOA-Uid": "attacker",
                "X-MOA-Name": "forged",
            }
            me = await connection.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200 and me.json()["data"]["uid"] == "123"
            assert "attacker" not in me.text and "forged" not in me.text
            session = await connection.post("/api/v1/auth/session", headers=headers)
            assert session.status_code == 200 and session.headers["cache-control"] == "no-store"
            assert session.json()["data"]["token"] == "renewed"
            created = await connection.post(
                "/api/v1/runs", headers=headers, json={"workflow_type": "query"}
            )
            assert created.status_code == 201
        finally:
            app.dependency_overrides.pop(get_auth_provider)


async def test_openapi_exposes_moa_authorization(client):
    connection, _ = client
    schema = (await connection.get("/openapi.json")).json()
    scheme = schema["components"]["securitySchemes"]["MOA"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-MOA-Token"
    for path, method in [
        ("/api/v1/runs", "post"),
        ("/api/v1/auth/me", "get"),
        ("/api/v1/auth/session", "post"),
    ]:
        assert {"MOA": []} in schema["paths"][path][method]["security"]
    assert not schema["paths"]["/health"]["get"].get("security")
    assert not schema["paths"]["/api/v1/auth/config"]["get"].get("security")
