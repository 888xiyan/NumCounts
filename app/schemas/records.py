from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RegisteredFunctionSpec(BaseModel):
    kind: Literal["registered"]
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)


class ExternalFunctionSpec(BaseModel):
    kind: Literal["external"]
    executor_id: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9-]{0,63}$"
    )
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)


FunctionSpec = Annotated[
    RegisteredFunctionSpec | ExternalFunctionSpec,
    Field(discriminator="kind"),
]


class CreateRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    period_id: str | None = Field(default=None, max_length=64)
    input: dict[str, Any]
    function: FunctionSpec


class CalculationErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class CalculationRecordResponse(BaseModel):
    id: str
    table_name: str
    period_id: str | None
    input: dict[str, Any]
    function: FunctionSpec
    output: dict[str, Any] | None
    status: Literal["pending", "running", "success", "failed"]
    error: CalculationErrorResponse | None
    attempt_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class CalculationRecordListResponse(BaseModel):
    data: list[CalculationRecordResponse]


class CalculationAttemptResponse(BaseModel):
    id: str
    record_id: str
    attempt_no: int
    execution_id: str
    executor_type: str
    status: Literal["running", "success", "failed"]
    input_snapshot: dict[str, Any]
    function_snapshot: dict[str, Any]
    output_snapshot: dict[str, Any] | None
    error_snapshot: dict[str, Any] | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None


class CalculationAttemptListResponse(BaseModel):
    data: list[CalculationAttemptResponse]


class RunPendingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=100)


class RunPendingResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    skipped: int
    records: list[CalculationRecordResponse]


class RegisteredFunctionResponse(BaseModel):
    kind: Literal["registered"] = "registered"
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class RegisteredFunctionListResponse(BaseModel):
    data: list[RegisteredFunctionResponse]
