from uuid import UUID

from fastapi import Depends, Response

from bi_wiki import __version__
from bi_wiki.api.deps import DatabaseDep, RunRepo, get_principal
from bi_wiki.api.responses import ApiRouter, ResponderDep
from bi_wiki.core.errors import ServiceError
from bi_wiki.models.responses import ApiResponse, HealthResponse
from bi_wiki.models.runs import RunCreate, RunRead
from bi_wiki.models.workflows import (
    ApprovalRequest,
    CancelRequest,
    IngestRequest,
    LintRequest,
    QueryRequest,
)

health_router = ApiRouter()
router = ApiRouter(dependencies=[Depends(get_principal)])


@health_router.get("/health", tags=["health"], response_model=ApiResponse[HealthResponse])
async def health(db: DatabaseDep, reply: ResponderDep) -> ApiResponse[HealthResponse]:
    await db.check()
    return reply.ok(
        HealthResponse(status="ok", service="bi-wiki-service", version=__version__, database="ok")
    )


@router.post("/api/v1/runs", status_code=201, response_model=ApiResponse[RunRead], tags=["runs"])
async def register_run(
    body: RunCreate, response: Response, repo: RunRepo, reply: ResponderDep
) -> ApiResponse[RunRead]:
    """只登记任务；queued 不表示已经派发或执行。"""
    run = await repo.create(body.workflow_type)
    response.headers["Location"] = f"/api/v1/runs/{run.run_id}"
    return reply.ok(run)


@router.get(
    "/api/v1/runs/{run_id}",
    response_model=ApiResponse[RunRead],
    tags=["runs"],
)
async def get_run(run_id: UUID, repo: RunRepo, reply: ResponderDep) -> ApiResponse[RunRead]:
    return reply.ok(await repo.get(run_id))


def not_implemented() -> None:
    raise ServiceError("FEATURE_NOT_IMPLEMENTED", "此能力尚未在当前阶段实现", 501)


@router.post(
    "/api/v1/ingests", tags=["reserved"], status_code=501, response_model=ApiResponse[None]
)
async def ingest(body: IngestRequest) -> None:
    not_implemented()


@router.post(
    "/api/v1/queries", tags=["reserved"], status_code=501, response_model=ApiResponse[None]
)
async def query(body: QueryRequest) -> None:
    not_implemented()


@router.post("/api/v1/lints", tags=["reserved"], status_code=501, response_model=ApiResponse[None])
async def lint(body: LintRequest) -> None:
    not_implemented()


@router.post(
    "/api/v1/runs/{run_id}/approve",
    tags=["reserved"],
    status_code=501,
    response_model=ApiResponse[None],
)
async def approve(run_id: UUID, body: ApprovalRequest) -> None:
    not_implemented()


@router.post(
    "/api/v1/runs/{run_id}/cancel",
    tags=["reserved"],
    status_code=501,
    response_model=ApiResponse[None],
)
async def cancel(run_id: UUID, body: CancelRequest) -> None:
    not_implemented()
