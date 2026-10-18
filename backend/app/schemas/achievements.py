from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.achievement import (
    AchievementSource,
    AchievementStatus,
    AchievementType,
)


class ImportedAchievement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_id: str = Field(min_length=1, max_length=128)
    teacher_id: str = Field(min_length=1, max_length=64)
    teacher_name: str = Field(min_length=1, max_length=128)
    department_id: str = Field(min_length=1, max_length=64)
    achievement_type: AchievementType
    level: str = Field(min_length=1, max_length=64)
    occurred_at: date
    payload: dict[str, Any] = Field(default_factory=dict)


class ImportAchievementsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        AchievementSource.ACADEMIC_AFFAIRS, AchievementSource.RESEARCH_SYSTEM
    ]
    records: list[ImportedAchievement] = Field(min_length=1, max_length=100)


class ManualDeclarationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: str = Field(min_length=1, max_length=64)
    achievement_type: AchievementType
    level: str = Field(min_length=1, max_length=64)
    occurred_at: date
    payload: dict[str, Any] = Field(default_factory=dict)


class ReviewAchievementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)


class AchievementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    teacher_id: str
    teacher_name: str
    department_id: str
    achievement_type: AchievementType
    level: str
    occurred_at: date
    source: AchievementSource
    source_record_id: str | None
    payload: dict[str, Any]
    status: AchievementStatus
    submitted_by_user_id: str | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    review_comment: str | None
    created_at: datetime
    updated_at: datetime


class AchievementListResponse(BaseModel):
    data: list[AchievementResponse]


class ImportAchievementsResponse(BaseModel):
    imported: int
    records: list[AchievementResponse]
