from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateRecordLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_id: str = Field(min_length=36, max_length=36)
    target_record_id: str = Field(min_length=36, max_length=36)
    link_type: Literal["data", "execution"]
    input_key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    target_path: str = Field(
        pattern=r"^(input|output)(\.[a-zA-Z][a-zA-Z0-9_]*)*$"
    )


class RecordLinkResponse(BaseModel):
    id: str
    source_record_id: str
    target_record_id: str
    link_type: Literal["data", "execution"]
    input_key: str
    target_path: str
    created_at: datetime


class RecordLinkListResponse(BaseModel):
    data: list[RecordLinkResponse]
