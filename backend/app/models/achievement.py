import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AchievementType(enum.StrEnum):
    TEACHING_WORKLOAD = "teaching_workload"
    RESEARCH_PAPER = "research_paper"
    RESEARCH_PROJECT = "research_project"
    RESEARCH_FUNDING = "research_funding"
    SOCIAL_SERVICE = "social_service"
    TALENT_CULTIVATION = "talent_cultivation"


class AchievementSource(enum.StrEnum):
    ACADEMIC_AFFAIRS = "academic_affairs"
    RESEARCH_SYSTEM = "research_system"
    MANUAL_DECLARATION = "manual_declaration"


class AchievementStatus(enum.StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AchievementRecord(Base):
    __tablename__ = "achievement_records"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_record_id", name="uk_achievement_source_record"
        ),
        Index("idx_achievement_status_occurred", "status", "occurred_at"),
        Index("idx_achievement_teacher_status", "teacher_id", "status"),
        Index("idx_achievement_department_status", "department_id", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    teacher_id: Mapped[str] = mapped_column(String(64), nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(128), nullable=False)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    achievement_type: Mapped[AchievementType] = mapped_column(
        String(32), nullable=False
    )
    level: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[date] = mapped_column(nullable=False)
    source: Mapped[AchievementSource] = mapped_column(String(32), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[AchievementStatus] = mapped_column(
        String(32), nullable=False, default=AchievementStatus.PENDING_REVIEW
    )
    submitted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
