"""Contracts for member special-performance and appeal cases."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.achievement import AchievementType


class CreateSpecialPerformanceCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_type: Literal["special_performance", "appeal"]
    title: str = Field(min_length=1, max_length=200)
    period_id: str | None = Field(default=None, min_length=1, max_length=64)
    teacher_name: str | None = Field(default=None, min_length=1, max_length=128)
    department_id: str | None = Field(default=None, min_length=1, max_length=64)
    original_result_id: str | None = Field(default=None, min_length=36, max_length=36)
    form_data: dict[str, Any] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_type_fields(self) -> "CreateSpecialPerformanceCaseRequest":
        if self.case_type == "appeal" and self.original_result_id is None:
            raise ValueError("appeals must reference an original formal result")
        if self.case_type == "special_performance" and self.original_result_id:
            raise ValueError(
                "special performance cases cannot reference an appeal result"
            )
        if self.case_type == "special_performance" and (
            self.period_id is None
            or self.teacher_name is None
            or self.department_id is None
        ):
            raise ValueError(
                "special performance cases require period, teacher name, and department"
            )
        return self


class UpdateSpecialPerformanceCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    form_data: dict[str, Any] | None = Field(default=None, min_length=1)
    teacher_name: str | None = Field(default=None, min_length=1, max_length=128)
    department_id: str | None = Field(default=None, min_length=1, max_length=64)


class HandleSpecialPerformanceCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["start_review", "return_to_draft"]
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_return_comment(self) -> "HandleSpecialPerformanceCaseRequest":
        if self.action == "return_to_draft" and not (self.comment or "").strip():
            raise ValueError("a comment is required when returning a case to draft")
        return self


class ReviewSpecialPerformanceCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "return_to_draft"]
    comment: str | None = Field(default=None, max_length=2000)
    plugin_id: str | None = Field(default=None, min_length=36, max_length=36)

    @model_validator(mode="after")
    def validate_review_action(self) -> "ReviewSpecialPerformanceCaseRequest":
        if self.action == "approve" and self.plugin_id is None:
            raise ValueError("approval requires a dedicated rule plugin")
        if self.action == "return_to_draft" and not (self.comment or "").strip():
            raise ValueError("a comment is required when returning a case to draft")
        return self


class AdjustSpecialPerformanceDeadlineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_due_at: datetime
    reason: str = Field(min_length=1, max_length=1000)


class SpecialPerformancePluginOutput(BaseModel):
    """The required normalized output from a special-case processing plugin."""

    model_config = ConfigDict(extra="forbid")

    achievement_type: AchievementType
    level: str = Field(min_length=1, max_length=64)
    occurred_at: date
    payload: dict[str, Any]


class SpecialPerformanceCaseMaterialResponse(BaseModel):
    id: str
    material_key: str
    version: int
    filename: str
    media_type: str
    sha256: str
    size_bytes: int
    is_current: bool
    created_at: datetime


class SpecialPerformanceCaseEventResponse(BaseModel):
    id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_user_id: str | None
    details: dict[str, Any]
    created_at: datetime


class SpecialPerformanceCaseResponse(BaseModel):
    id: str
    case_type: Literal["special_performance", "appeal"]
    status: Literal["draft", "submitted", "reviewing", "approved", "processed"]
    submitted_by_user_id: str
    teacher_id: str
    teacher_name: str
    department_id: str
    period_id: str
    original_result_id: str | None
    title: str
    form_data: dict[str, Any]
    submitted_snapshot: dict[str, Any] | None
    submission_version: int
    submitted_at: datetime | None
    review_due_at: datetime | None
    overdue: bool
    processed_by_user_id: str | None
    reviewed_by_user_id: str | None
    processing_comment: str | None
    review_comment: str | None
    plugin_id: str | None
    plugin_snapshot: dict[str, Any] | None
    plugin_execution_status: str | None
    calculation_record_id: str | None
    achievement_id: str | None
    processing_error: dict[str, Any] | None
    materials: list[SpecialPerformanceCaseMaterialResponse] = Field(
        default_factory=list
    )
    events: list[SpecialPerformanceCaseEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SpecialPerformanceCaseListResponse(BaseModel):
    data: list[SpecialPerformanceCaseResponse]
