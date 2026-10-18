import pytest
from pydantic import ValidationError

from app.core.errors import APIError
from app.schemas.records import CreateRecordRequest, PluginFunctionSpec
from app.schemas.workflows import (
    CreateWorkflowDefinitionRequest,
    PluginWorkflowNodeConfig,
)
from app.services.workflow_service import resolve_input_bindings


def test_plugin_reference_is_json_not_embedded_source() -> None:
    request = CreateRecordRequest.model_validate(
        {
            "table_name": "teaching_results",
            "input": {"hours": 36},
            "function": {
                "kind": "plugin",
                "plugin_id": "11111111-1111-1111-1111-111111111111",
            },
        }
    )

    assert isinstance(request.function, PluginFunctionSpec)
    assert request.function.plugin_id == "11111111-1111-1111-1111-111111111111"


def test_workflow_requires_aggregate_sources_to_precede_aggregate_node() -> None:
    with pytest.raises(ValidationError, match="preceding nodes"):
        CreateWorkflowDefinitionRequest.model_validate(
            {
                "workflow_key": "annual_performance",
                "version": "1.0.0",
                "name": "年度绩效",
                "nodes": [
                    {
                        "node_key": "total",
                        "node_type": "aggregate",
                        "config": {
                            "table_name": "performance_summary",
                            "source_node_keys": ["teaching"],
                        },
                    },
                    {
                        "node_key": "teaching",
                        "node_type": "plugin",
                        "config": {
                            "plugin_id": "11111111-1111-1111-1111-111111111111",
                            "table_name": "teaching_results",
                        },
                    },
                ],
            }
        )


def test_workflow_resolves_only_explicit_context_or_literals() -> None:
    config = PluginWorkflowNodeConfig.model_validate(
        {
            "plugin_id": "11111111-1111-1111-1111-111111111111",
            "table_name": "teaching_results",
            "input_bindings": {
                "hours": {"kind": "context", "key": "approved_hours"},
                "rate": {"kind": "literal", "value": 80},
            },
        }
    )

    assert resolve_input_bindings(config, {"approved_hours": 36}) == {
        "hours": 36,
        "rate": 80,
    }

    with pytest.raises(APIError) as error:
        resolve_input_bindings(config, {})
    assert error.value.detail["code"] == "WORKFLOW_CONTEXT_VALUE_MISSING"
