"""Shared response construction and OpenAPI error declarations."""

from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bi_wiki.models.responses import ApiResponse, ValidationDetail

T = TypeVar("T")

# These errors form the shared application contract. HTTP status remains meaningful.
ERROR_RESPONSES = {
    status: {"model": ApiResponse[None]}
    for status in (400, 401, 403, 404, 405, 409, 413, 415, 422, 500, 501, 503)
}


class ApiRouter(APIRouter):
    def __init__(self, **kwargs):
        responses = {**ERROR_RESPONSES, **kwargs.pop("responses", {})}
        super().__init__(responses=responses, **kwargs)


class Responder:
    def __init__(self, request: Request):
        self.request_id = request.state.request_id

    def ok(self, data: T) -> ApiResponse[T]:
        return ApiResponse(code="OK", message="操作成功", data=data, request_id=self.request_id)


def get_responder(request: Request) -> Responder:
    return Responder(request)


ResponderDep = Annotated[Responder, Depends(get_responder)]


def error_response(
    request: Request,
    code: str,
    message: str,
    status: int,
    *,
    details: list[ValidationDetail] | None = None,
    headers: dict | None = None,
) -> JSONResponse:
    request_id = request.state.request_id
    body = ApiResponse[None](
        code=code, message=message, data=None, request_id=request_id, details=details or []
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        headers={**(headers or {}), "X-Request-ID": request_id},
    )
