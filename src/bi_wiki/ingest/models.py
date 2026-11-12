"""Versioned ontology v1 contracts. Candidates are never executable instructions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["concept", "entity", "metric", "rule", "data_asset"]
RelationKind = Literal["measures", "constrained_by", "maps_to", "depends_on", "related_to"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(StrictModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=8000)


class Relation(StrictModel):
    type: RelationKind
    target_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    evidence: Evidence


class Candidate(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,79}$")
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    definition: str = Field(min_length=1, max_length=8000)
    scope: str = Field(min_length=1, max_length=1000)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=30)
    unknowns: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[Evidence] = Field(min_length=1, max_length=20)
    relations: list[Relation] = Field(default_factory=list, max_length=30)
    target_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)


class Extraction(StrictModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=30)
    notes: list[str] = Field(default_factory=list, max_length=30)


class WorkflowConfig(StrictModel):
    name: str = Field(default="文档知识提取", min_length=1, max_length=100)
    instructions: str = Field(
        default="提取资料明确支持的业务定义和关系；未说明的内容记录为不确定项。", max_length=8000
    )
    kinds: list[Kind] = Field(
        default_factory=lambda: ["concept", "entity", "metric", "rule", "data_asset"],
        min_length=1,
        max_length=5,
    )
    max_candidates: int = Field(default=15, ge=1, le=30)


class SourceUpload(StrictModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=180000)


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    sha256: str
    size_bytes: int
    created_at: datetime


class StartIngest(StrictModel):
    source_id: UUID
    idempotency_key: UUID
    reprocess: bool = False


class ApprovePlan(StrictModel):
    plan_version: int = Field(ge=1)
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class RejectPlan(ApprovePlan):
    reason: str = Field(min_length=1, max_length=1000)
