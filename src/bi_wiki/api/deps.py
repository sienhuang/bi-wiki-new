"""HTTP dependencies; lifespan owns resource creation and disposal."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from bi_wiki.core.config import Settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.db.database import Database
from bi_wiki.repositories.runs import RunRepository
from bi_wiki.services.auth import MoaAuthProvider, Principal


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_run_repository(request: Request) -> RunRepository:
    return request.app.state.runs


DatabaseDep = Annotated[Database, Depends(get_database)]
RunRepo = Annotated[RunRepository, Depends(get_run_repository)]


def get_auth_provider(request: Request) -> MoaAuthProvider:
    return request.app.state.auth_provider


AuthProviderDep = Annotated[MoaAuthProvider, Depends(get_auth_provider)]


moa_token_header = APIKeyHeader(
    name="X-MOA-Token",
    scheme_name="MOA",
    description=(
        "填写 MOA 登录后的 token 原文，不添加 Bearer 前缀。Swagger 不会自动读取前端登录状态。"
    ),
    auto_error=False,
)


def get_moa_token(x_moa_token: Annotated[str | None, Depends(moa_token_header)]) -> str:
    if not x_moa_token:
        raise ServiceError("AUTH_TOKEN_MISSING", "缺少 X-MOA-Token，请先提供登录凭据", 401)
    return x_moa_token


MoaToken = Annotated[str, Depends(get_moa_token)]


async def get_principal(provider: AuthProviderDep, token: MoaToken) -> Principal:
    return await provider.authenticate(token)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
