from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContextInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["context"]
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")


class LiteralInputBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["literal"]
    value: Any


WorkflowInputBinding = Annotated[
    ContextInputBinding | LiteralInputBinding,
    Field(discriminator="kind"),
]


class PluginWorkflowNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str = Field(min_length=36, max_length=36)
    table_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    input_bindings: dict[str, WorkflowInputBinding] = Field(default_factory=dict)


class AggregateWorkflowNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    source_node_keys: list[str] = Field(min_length=1, max_length=100)


class PluginWorkflowNodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    node_type: Literal["plugin"]
    config: PluginWorkflowNodeConfig


class AggregateWorkflowNodeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    node_type: Literal["aggregate"]
    config: AggregateWorkflowNodeConfig


WorkflowNodeDefinition = Annotated[
    PluginWorkflowNodeDefinition | AggregateWorkflowNodeDefinition,
    Field(discriminator="node_type"),
]


class CreateWorkflowDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    version: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    nodes: list[WorkflowNodeDefinition] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_sequence(self) -> "CreateWorkflowDefinitionRequest":
        known_nodes: set[str] = set()
        for node in self.nodes:
            if node.node_key in known_nodes:
                raise ValueError(f"duplicate node_key: {node.node_key}")
            if isinstance(node, AggregateWorkflowNodeDefinition):
                missing = [
                    key
                    for key in node.config.source_node_keys
                    if key not in known_nodes
                ]
                if missing:
                    raise ValueError(
                        "aggregate nodes can only reference preceding nodes: "
                        + ", ".join(missing)
                    )
            known_nodes.add(node.node_key)
        return self


class WorkflowNodeResponse(BaseModel):
    id: str
    node_key: str
    node_type: Literal["plugin", "aggregate"]
    position: int
    config: dict[str, Any]
    plugin: dict[str, Any] | None = None


class WorkflowDefinitionResponse(BaseModel):
    id: str
    workflow_key: str
    version: str
    name: str
    description: str
    status: Literal["draft", "active", "disabled"]
    nodes: list[WorkflowNodeResponse]
    created_at: datetime
    updated_at: datetime


class WorkflowDefinitionListResponse(BaseModel):
    data: list[WorkflowDefinitionResponse]


class StartWorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_id: str | None = Field(default=None, max_length=64)
    context: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunNodeResponse(BaseModel):
    id: str
    node_key: str
    node_type: Literal["plugin", "aggregate"]
    status: Literal["pending", "running", "success", "failed", "skipped"]
    calculation_record_id: str | None
    input_snapshot: dict[str, Any] | None
    output_snapshot: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    workflow_key: str
    workflow_version: str
    period_id: str | None
    context: dict[str, Any]
    status: Literal["running", "success", "failed"]
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    requested_by_user_id: str
    started_at: datetime
    finished_at: datetime | None
    nodes: list[WorkflowRunNodeResponse]


class WorkflowRunListResponse(BaseModel):
    data: list[WorkflowRunResponse]
