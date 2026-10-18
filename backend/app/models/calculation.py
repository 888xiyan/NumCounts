import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CalculationRecord(Base):
    __tablename__ = "calculation_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uk_records_idempotency_key"),
        Index("idx_records_status_created", "status", "created_at"),
        Index("idx_records_table_period", "table_name", "period_id"),
        Index("idx_records_status_period", "status", "period_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    table_name: Mapped[str] = mapped_column(String(64), nullable=False)
    period_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    function_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    plugin_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rule_plugins.id"), nullable=True
    )
    plugin_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class CalculationAttempt(Base):
    __tablename__ = "calculation_attempts"
    __table_args__ = (
        UniqueConstraint("record_id", "attempt_no", name="uk_attempt_record_no"),
        UniqueConstraint("execution_id", name="uk_attempt_execution_id"),
        Index("idx_attempt_record_started", "record_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calculation_records.id"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_id: Mapped[str] = mapped_column(String(36), nullable=False)
    executor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    function_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
