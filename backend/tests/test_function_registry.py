import pytest

from app.functions import (
    FunctionExecutionError,
    FunctionNotFoundError,
    execute_registered_function,
    get_registered_function,
    list_registered_functions,
)


def test_registry_exposes_versioned_approved_functions() -> None:
    assert [(item.name, item.version) for item in list_registered_functions()] == [
        ("aggregate_amounts", "1.0.0"),
        ("course_bonus", "1.0.0"),
        ("research_performance", "1.0.0"),
        ("teaching_performance", "1.0.0"),
    ]
    assert get_registered_function("teaching_performance", "1.0.0").metadata()[
        "kind"
    ] == "registered"


def test_registered_function_executes_without_embedded_source_code() -> None:
    output = execute_registered_function(
        {"kind": "registered", "name": "teaching_performance", "version": "1.0.0"},
        {"hours": 36, "rate": 80, "quality_factor": 1.1},
    )

    assert output["amount"] == 3168.0
    assert output["metric"] == "teaching_performance"


def test_aggregate_function_is_a_normal_auditable_calculation() -> None:
    output = execute_registered_function(
        {"kind": "registered", "name": "aggregate_amounts", "version": "1.0.0"},
        {"amounts": [3168, 12000.5]},
    )

    assert output == {
        "metric": "aggregate_amounts",
        "amount": 15168.5,
        "formula": "sum(amounts)",
    }


def test_registered_function_reports_invalid_input_as_domain_error() -> None:
    with pytest.raises(FunctionExecutionError) as error:
        execute_registered_function(
            {"kind": "registered", "name": "course_bonus", "version": "1.0.0"},
            {"course_count": 1, "level": "municipal"},
        )

    assert error.value.code == "INVALID_FUNCTION_INPUT"


def test_unknown_function_is_not_executable() -> None:
    with pytest.raises(FunctionNotFoundError):
        get_registered_function("arbitrary_python", "1.0.0")
