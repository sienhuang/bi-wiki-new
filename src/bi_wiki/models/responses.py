"""One JSON envelope for all application API responses."""

from typing import Literal

from pydantic import BaseModel, Field


class ValidationDetail(BaseModel):
    location: list[str | int]
    type: str


class ApiResponse[T](BaseModel):
    code: str
    message: str
    data: T
    request_id: str
    details: list[ValidationDetail] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    database: Literal["ok"]


class AuthConfig(BaseModel):
    portal_url: str
    project_id: int
