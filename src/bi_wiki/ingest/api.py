from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from pydantic import ValidationError

from bi_wiki.api.deps import PrincipalDep
from bi_wiki.api.responses import ApiRouter, ResponderDep
from bi_wiki.core.errors import ServiceError
from bi_wiki.ingest.models import ApprovePlan, RejectPlan, SourceUpload, StartIngest, WorkflowConfig
from bi_wiki.ingest.service import IngestService
from bi_wiki.models.responses import ApiResponse


def get_ingest(request: Request) -> IngestService:
    return request.app.state.ingest


IngestDep = Annotated[IngestService, Depends(get_ingest)]
router = ApiRouter(prefix="/api/v1", tags=["knowledge"])


@router.post(
    "/sources",
    response_model=ApiResponse[dict],
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": SourceUpload.model_json_schema()}},
        }
    },
)
async def upload(request: Request, user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 200000:
            raise ServiceError("SOURCE_LIMIT", "上传请求不能超过 200000 字节", 413)
    try:
        body = SourceUpload.model_validate_json(data)
    except ValidationError:
        raise ServiceError(
            "INVALID_SOURCE", "上传参数无效，需要 filename 和 content_base64", 422
        ) from None
    return reply.ok(await service.upload(user.uid, body))


@router.get("/sources", response_model=ApiResponse[list])
async def sources(user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.list_sources(user.uid))


@router.get("/sources/{source_id}", response_model=ApiResponse[dict])
async def source(source_id: UUID, user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.read_source(user.uid, source_id))


@router.get("/ingest-config", response_model=ApiResponse[dict])
async def config(user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.config(user.uid))


@router.post("/ingest-config", response_model=ApiResponse[dict], status_code=201)
async def publish_config(
    body: WorkflowConfig, user: PrincipalDep, service: IngestDep, reply: ResponderDep
):
    return reply.ok(await service.save_config(user.uid, body))


@router.post("/ingests", response_model=ApiResponse[dict])
async def start(body: StartIngest, user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    """同步生成计划，执行期限由服务端配置决定；断线后按请求键只读查询原任务。"""
    return reply.ok(await service.start(user.uid, body))


@router.get("/ingests", response_model=ApiResponse[list])
async def ingests(user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.list_runs(user.uid))


@router.get("/ingest-requests/{key}", response_model=ApiResponse[dict])
async def by_request(key: UUID, user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.by_request(user.uid, key))


@router.get("/ingests/{run_id}", response_model=ApiResponse[dict])
async def detail(run_id: UUID, user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.detail(user.uid, run_id))


@router.post("/runs/{run_id}/approve", response_model=ApiResponse[dict])
async def approve(
    run_id: UUID, body: ApprovePlan, user: PrincipalDep, service: IngestDep, reply: ResponderDep
):
    return reply.ok(await service.decide(user.uid, run_id, body, True))


@router.post("/runs/{run_id}/reject", response_model=ApiResponse[dict])
async def reject(
    run_id: UUID, body: RejectPlan, user: PrincipalDep, service: IngestDep, reply: ResponderDep
):
    return reply.ok(await service.decide(user.uid, run_id, body, False))


@router.get("/definitions", response_model=ApiResponse[list])
async def definitions(user: PrincipalDep, service: IngestDep, reply: ResponderDep):
    return reply.ok(await service.definitions(user.uid))


@router.get("/definitions/{definition_id}", response_model=ApiResponse[dict])
async def definition(
    definition_id: UUID, user: PrincipalDep, service: IngestDep, reply: ResponderDep
):
    return reply.ok(await service.definition(user.uid, definition_id))
