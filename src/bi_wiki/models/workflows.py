"""预留工作流的输入契约；第一阶段不读取来源或执行模型。"""

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IngestRequest(RequestModel):
    source_ref: str = Field(min_length=1, max_length=1024)


class QueryRequest(RequestModel):
    question: str = Field(min_length=1, max_length=16000)
    scope: list[str] = Field(default_factory=list, max_length=100)


class LintRequest(RequestModel):
    scope: list[str] = Field(default_factory=list, max_length=100)


class ApprovalRequest(RequestModel):
    plan_version: int = Field(ge=1)


class CancelRequest(RequestModel):
    reason: str | None = Field(default=None, max_length=1000)
