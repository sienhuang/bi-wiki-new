"""MOA identity is verified server-side; never trust client identity headers."""

import httpx
from pydantic import BaseModel

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError


class Principal(BaseModel):
    uid: str
    name: str = ""
    nick: str = ""


class AuthSession(BaseModel):
    token: str
    user: Principal


def unauthorized() -> ServiceError:
    return ServiceError("UNAUTHENTICATED", "登录已失效，请重新登录", 401)


class MoaAuthProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def _post(self, url: str, token: str) -> dict:
        if not token or len(token) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise unauthorized()
        try:
            response = await self.client.post(url, json={"token": token})
            if response.status_code in (401, 403):
                raise unauthorized()
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise ServiceError("AUTH_UNAVAILABLE", "认证服务暂时不可用，请稍后重试", 503) from None
        if not isinstance(data, dict) or type(data.get("code")) is not int:
            raise ServiceError("AUTH_UNAVAILABLE", "认证服务响应异常", 503)
        if data["code"] != 0:
            raise unauthorized()
        result = data.get("result")
        if not isinstance(result, dict):
            raise ServiceError("AUTH_UNAVAILABLE", "认证服务响应异常", 503)
        if str(result.get("project")) != str(self.settings.moa_project_id):
            raise ServiceError("AUTH_PROJECT_MISMATCH", "当前账号无此应用访问权限", 403)
        return result

    async def authenticate(self, token: str) -> Principal:
        result = await self._post(f"{self.settings.moa_auth_url}/api/getinfo", token)
        uid = result.get("uid")
        if isinstance(uid, bool) or not isinstance(uid, (int, str)) or not str(uid).strip():
            raise ServiceError("AUTH_IDENTITY_MISSING", "认证服务未返回有效身份", 503)
        if str(uid) == "0":
            raise unauthorized()
        return Principal(
            uid=str(uid), name=str(result.get("name") or ""), nick=str(result.get("nick") or "")
        )

    async def refresh(self, token: str) -> AuthSession:
        # Check original identity before refreshing, then validate the replacement token.
        original = await self.authenticate(token)
        result = await self._post(f"{self.settings.moa_portal_url}/api/refresh", token)
        refreshed = result.get("token")
        if not isinstance(refreshed, str) or not refreshed:
            raise ServiceError("AUTH_UNAVAILABLE", "认证服务未返回有效凭据", 503)
        user = await self.authenticate(refreshed)
        if user.uid != original.uid:
            raise unauthorized()
        return AuthSession(token=refreshed, user=user)
