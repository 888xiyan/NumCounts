from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.achievement import AchievementType


class AchievementInputMapping(BaseModel):
    """A fixed aggregation from approved achievement records to workflow context."""

    model_config = ConfigDict(extra="forbid")

    context_key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    aggregation: Literal["count", "sum"]
    achievement_type: AchievementType | None = None
    level: str | None = Field(default=None, min_length=1, max_length=64)
    payload_key: str | None = Field(
        default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$"
    )

    @model_validator(mode="after")
    def validate_payload_key(self) -> "AchievementInputMapping":
        if self.aggregation == "sum" and self.payload_key is None:
            raise ValueError("sum mappings require payload_key")
        if self.aggregation == "count" and self.payload_key is not None:
            raise ValueError("count mappings cannot include payload_key")
        return self


class CreateFormalCalculationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_id: str = Field(min_length=1, max_length=64)
    occurred_from: date
    occurred_to: date
    department_id: str | None = Field(default=None, min_length=1, max_length=64)
    teacher_ids: list[str] = Field(default_factory=list, max_length=1000)
    workflow_id: str = Field(min_length=36, max_length=36)
    result_node_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    input_mappings: list[AchievementInputMapping] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_scope_and_mappings(self) -> "CreateFormalCalculationBatchRequest":
        if self.occurred_from > self.occurred_to:
            raise ValueError("occurred_from cannot be after occurred_to")
        if len(self.teacher_ids) != len(set(self.teacher_ids)):
            raise ValueError("teacher_ids must not contain duplicates")
        mapping_keys = [item.context_key for item in self.input_mappings]
        if len(mapping_keys) != len(set(mapping_keys)):
            raise ValueError("input_mappings must not repeat context_key")
        return self


class ReviewFormalCalculationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm"]


class FormalCalculationErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class FormalCalculationResultSourceResponse(BaseModel):
    id: str
    achievement_id: str
    achievement: dict[str, Any]
    created_at: datetime


class FormalCalculationResultResponse(BaseModel):
    id: str
    batch_id: str
    teacher_id: str
    teacher_name: str
    department_id: str
    period_id: str
    result_version: int
    workflow_run_id: str | None
    status: Literal["running", "success", "failed"]
    total_amount: float | None
    result: dict[str, Any] | None
    error: FormalCalculationErrorResponse | None
    created_at: datetime
    finished_at: datetime | None
    sources: list[FormalCalculationResultSourceResponse] = Field(default_factory=list)


class FormalCalculationResultListResponse(BaseModel):
    data: list[FormalCalculationResultResponse]


class FormalCalculationBatchResponse(BaseModel):
    id: str
    period_id: str
    occurred_from: date
    occurred_to: date
    department_id: str | None
    teacher_ids: list[str]
    workflow: dict[str, Any]
    input_mappings: list[dict[str, Any]]
    result_node_key: str
    status: Literal["running", "pending_review", "reviewed", "failed"]
    created_by_user_id: str
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    error: FormalCalculationErrorResponse | None
    created_at: datetime
    finished_at: datetime | None
    results: list[FormalCalculationResultResponse] = Field(default_factory=list)


class FormalCalculationBatchListResponse(BaseModel):
    data: list[FormalCalculationBatchResponse]
