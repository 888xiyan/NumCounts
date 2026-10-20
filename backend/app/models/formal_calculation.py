import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FormalCalculationBatchStatus(enum.StrEnum):
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"
    FAILED = "failed"


class FormalCalculationResultStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class FormalCalculationBatch(Base):
    __tablename__ = "formal_calculation_batches"
    __table_args__ = (
        Index("idx_formal_batches_period_created", "period_id", "created_at"),
        Index("idx_formal_batches_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    period_id: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_from: Mapped[date] = mapped_column(nullable=False)
    occurred_to: Mapped[date] = mapped_column(nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    teacher_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflow_definitions.id"), nullable=False
    )
    workflow_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_mappings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    result_node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[FormalCalculationBatchStatus] = mapped_column(
        String(32), nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)


class FormalCalculationResult(Base):
    __tablename__ = "formal_calculation_results"
    __table_args__ = (
        UniqueConstraint(
            "batch_id", "teacher_id", name="uk_formal_result_batch_teacher"
        ),
        UniqueConstraint(
            "period_id", "teacher_id", "result_version", name="uk_formal_result_version"
        ),
        Index("idx_formal_results_period_teacher", "period_id", "teacher_id"),
        Index("idx_formal_results_batch", "batch_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("formal_calculation_batches.id"), nullable=False
    )
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_runs.id"), nullable=True
    )
    status: Mapped[FormalCalculationResultStatus] = mapped_column(
        String(16), nullable=False
    )
    total_amount: Mapped[float | None] = mapped_column(nullable=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)


class FormalCalculationResultSource(Base):
    __tablename__ = "formal_calculation_result_sources"
    __table_args__ = (
        UniqueConstraint("result_id", "achievement_id", name="uk_formal_result_source"),
        Index("idx_formal_sources_achievement", "achievement_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    result_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("formal_calculation_results.id"), nullable=False
    )
    achievement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("achievement_records.id"), nullable=False
    )
    achievement_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
