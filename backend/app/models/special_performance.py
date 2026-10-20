"""Material-backed special-performance and appeal cases."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import DATETIME, JSON, MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SpecialPerformanceCaseType(enum.StrEnum):
    SPECIAL_PERFORMANCE = "special_performance"
    APPEAL = "appeal"


class SpecialPerformanceCaseStatus(enum.StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    PROCESSED = "processed"


class SpecialPerformanceCase(Base):
    __tablename__ = "special_performance_cases"
    __table_args__ = (
        Index("idx_special_cases_status_due", "status", "review_due_at"),
        Index("idx_special_cases_owner_created", "submitted_by_user_id", "created_at"),
        Index("idx_special_cases_teacher_period", "teacher_id", "period_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_type: Mapped[SpecialPerformanceCaseType] = mapped_column(
        String(32), nullable=False
    )
    status: Mapped[SpecialPerformanceCaseStatus] = mapped_column(
        String(16), nullable=False
    )
    submitted_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period_id: Mapped[str] = mapped_column(String(64), nullable=False)
    original_result_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("formal_calculation_results.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    form_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    submitted_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    submission_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    review_due_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=6), nullable=True
    )
    processed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    processing_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    plugin_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rule_plugins.id"), nullable=True
    )
    plugin_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    plugin_execution_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    calculation_record_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calculation_records.id"), nullable=True
    )
    achievement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("achievement_records.id"), nullable=True
    )
    processing_error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class SpecialPerformanceCaseMaterial(Base):
    __tablename__ = "special_performance_case_materials"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "material_key", "version", name="uk_special_material_version"
        ),
        Index("idx_special_materials_case_current", "case_id", "is_current"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("special_performance_cases.id"), nullable=False
    )
    material_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = mapped_column(MEDIUMBLOB, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)


class SpecialPerformanceCaseEvent(Base):
    __tablename__ = "special_performance_case_events"
    __table_args__ = (
        Index("idx_special_case_events_case_created", "case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("special_performance_cases.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
