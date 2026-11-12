"""Additive v1 tables; publication and revision journal share one PG transaction."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bi_wiki.db.models import Base, utc_now


class SourceORM(Base):
    __tablename__ = "ontology_source"
    __table_args__ = (UniqueConstraint("owner", "sha256"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConfigORM(Base):
    __tablename__ = "ontology_config"
    __table_args__ = (UniqueConstraint("owner", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IngestORM(Base):
    __tablename__ = "ontology_ingest"
    __table_args__ = (UniqueConstraint("owner", "idempotency_key"),)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("wiki_run.run_id"), primary_key=True)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("ontology_source.id"))
    idempotency_key: Mapped[UUID]
    request_hash: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSONB)
    plan: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    publication_errors: Mapped[list] = mapped_column(JSONB, default=list)
    decision: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DefinitionORM(Base):
    __tablename__ = "ontology_definition"
    __table_args__ = (UniqueConstraint("owner", "key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner: Mapped[str] = mapped_column(String(200), index=True)
    key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    markdown: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RevisionORM(Base):
    __tablename__ = "ontology_revision"
    __table_args__ = (UniqueConstraint("definition_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    definition_id: Mapped[UUID] = mapped_column(ForeignKey("ontology_definition.id"))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("wiki_run.run_id"))
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RequestORM(Base):
    __tablename__ = "ontology_ingest_request"
    owner: Mapped[str] = mapped_column(String(200), primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("wiki_run.run_id"))
