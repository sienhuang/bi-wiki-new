from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RunORM(Base):
    __tablename__ = "wiki_run"
    __table_args__ = (
        CheckConstraint("workflow_type IN ('ingest','query','lint')", name="ck_run_workflow"),
        CheckConstraint(
            "status IN ('queued','running','awaiting_approval','succeeded','failed','cancelled')",
            name="ck_run_status",
        ),
        CheckConstraint("version >= 1", name="ck_run_version"),
        CheckConstraint(
            "(status IN ('succeeded','failed','cancelled')) = (completed_at IS NOT NULL)",
            name="ck_run_completed",
        ),
        CheckConstraint(
            "status NOT IN ('running','awaiting_approval','succeeded','failed') "
            "OR started_at IS NOT NULL",
            name="ck_run_started",
        ),
        CheckConstraint(
            "status != 'awaiting_approval' OR workflow_type = 'ingest'",
            name="ck_run_approval_workflow",
        ),
        CheckConstraint("(status = 'failed') = (error IS NOT NULL)", name="ck_run_error"),
    )

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="registered", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ref: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
