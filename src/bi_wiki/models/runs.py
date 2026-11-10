from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowType(StrEnum):
    INGEST = "ingest"
    QUERY = "query"
    LINT = "lint"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
ALLOWED_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.AWAITING_APPROVAL,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.AWAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.CANCELLED},
}


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_type: WorkflowType


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1024)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    run_id: UUID
    workflow_type: WorkflowType
    status: RunStatus
    stage: str
    version: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_ref: str | None = None
    error: RunError | None = None
