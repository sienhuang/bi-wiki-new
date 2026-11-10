from fastapi import Response

from bi_wiki.api.deps import AuthProviderDep, MoaToken, PrincipalDep, SettingsDep
from bi_wiki.api.responses import ApiRouter, ResponderDep
from bi_wiki.models.responses import ApiResponse, AuthConfig
from bi_wiki.services.auth import AuthSession, Principal

router = ApiRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/config", response_model=ApiResponse[AuthConfig])
async def auth_config(config: SettingsDep, reply: ResponderDep) -> ApiResponse[AuthConfig]:
    return reply.ok(AuthConfig(portal_url=config.moa_portal_url, project_id=config.moa_project_id))


@router.post("/session", response_model=ApiResponse[AuthSession])
async def session(
    provider: AuthProviderDep, token: MoaToken, response: Response, reply: ResponderDep
) -> ApiResponse[AuthSession]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return reply.ok(await provider.refresh(token))


@router.get("/me", response_model=ApiResponse[Principal])
async def me(user: PrincipalDep, response: Response, reply: ResponderDep) -> ApiResponse[Principal]:
    response.headers["Cache-Control"] = "no-store"
    return reply.ok(user)
