from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from bi_wiki import __version__
from bi_wiki.api.auth import router as auth_router
from bi_wiki.api.responses import error_response
from bi_wiki.api.routes import health_router, router
from bi_wiki.core.config import Settings, get_settings
from bi_wiki.core.errors import ServiceError
from bi_wiki.core.logging import logger, setup_logging
from bi_wiki.core.request_logging import RequestLoggingMiddleware
from bi_wiki.db.database import Database
from bi_wiki.models.responses import ValidationDetail
from bi_wiki.repositories.runs import RunRepository
from bi_wiki.services.auth import MoaAuthProvider


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        config = settings or get_settings()
        setup_logging(
            config.log_level, log_file=config.log_file, backup_count=config.log_backup_count
        )
        database = Database(config)
        application.state.settings = config
        application.state.database = database
        application.state.runs = RunRepository(database.sessions)
        auth_client = httpx.AsyncClient(timeout=config.moa_timeout_seconds, follow_redirects=False)
        application.state.auth_provider = MoaAuthProvider(config, auth_client)
        try:
            if config.initialize_database:
                await database.initialize()
            await database.check()
            logger.info("service_started")
            yield
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.error(
                "database_lifecycle_failed", exc_info=True, extra={"error_type": type(exc).__name__}
            )
            raise RuntimeError("DATABASE_UNAVAILABLE: 数据库初始化或连接失败，请检查配置") from None
        finally:
            await auth_client.aclose()
            await database.close()
            logger.info("service_stopped")

    application = FastAPI(title="BI Wiki Service", version=__version__, lifespan=lifespan)

    application.add_middleware(RequestLoggingMiddleware)

    @application.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return error_response(request, exc.code, exc.message, exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # 不将 Pydantic 的 input / ctx 原样返回，避免回显正文、令牌或敏感输入。
        details = [
            ValidationDetail(location=list(issue["loc"]), type=issue["type"])
            for issue in exc.errors()
        ]
        return error_response(request, "VALIDATION_ERROR", "请求参数无效", 422, details=details)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request, "HTTP_ERROR", "请求路径或方法不受支持", exc.status_code, headers=exc.headers
        )

    @application.exception_handler(SQLAlchemyError)
    @application.exception_handler(OSError)
    @application.exception_handler(TimeoutError)
    async def database_error(request: Request, exc: Exception):
        logger.error(
            "database_request_failed",
            exc_info=True,
            extra={"request_id": request.state.request_id, "error_type": type(exc).__name__},
        )
        return error_response(request, "DATABASE_UNAVAILABLE", "数据库暂时不可用", 503)

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "request_failed",
            exc_info=True,
            extra={"request_id": request.state.request_id, "error_type": type(exc).__name__},
        )
        return error_response(request, "INTERNAL_ERROR", "服务内部错误", 500)

    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(router)
    return application


app = create_app()
