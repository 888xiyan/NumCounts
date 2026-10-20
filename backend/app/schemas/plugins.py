from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.records import ExecutableFunctionSpec


class CreateRulePluginRequest(BaseModel):
    """A versioned, declarative shortcut for an executable function."""

    model_config = ConfigDict(extra="forbid")

    plugin_key: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
        description="Stable plugin name; create a new version instead of editing one.",
    )
    version: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    function: ExecutableFunctionSpec
    input_defaults: dict[str, Any] = Field(default_factory=dict)
    purpose: Literal["general", "special_case"] = "general"


class RulePluginResponse(BaseModel):
    id: str
    plugin_key: str
    version: str
    name: str
    description: str
    function: ExecutableFunctionSpec
    input_defaults: dict[str, Any]
    purpose: Literal["general", "special_case"]
    status: Literal["enabled", "disabled"]
    created_at: datetime
    updated_at: datetime


class RulePluginListResponse(BaseModel):
    data: list[RulePluginResponse]
