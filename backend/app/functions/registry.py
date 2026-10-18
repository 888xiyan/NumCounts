"""The allow-list of safe, versioned performance calculation functions.

Function specifications stored in records select one of these functions.  They
never contain executable Python or JavaScript, which keeps the table model
configurable without turning it into a code-execution surface.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class FunctionExecutionError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class FunctionNotFoundError(FunctionExecutionError):
    def __init__(self, name: str, version: str):
        super().__init__(
            "FUNCTION_NOT_FOUND",
            "registered function was not found",
            {"name": name, "version": version},
        )


class _TeachingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: float = Field(ge=0)
    rate: float = Field(ge=0)
    quality_factor: float = Field(default=1, ge=0)


class _CourseBonusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_count: int = Field(ge=0)
    level: Literal["national", "provincial", "school"]


class _ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papers: int = Field(default=0, ge=0)
    projects: int = Field(default=0, ge=0)
    funding: float = Field(default=0, ge=0)
    paper_weight: float = Field(default=100, ge=0)
    project_weight: float = Field(default=500, ge=0)
    funding_rate: float = Field(default=0.01, ge=0)


def _teaching_performance(value: _TeachingInput) -> dict[str, Any]:
    amount = round(value.hours * value.rate * value.quality_factor, 2)
    return {
        "metric": "teaching_performance",
        "amount": amount,
        "formula": "hours * rate * quality_factor",
    }


def _course_bonus(value: _CourseBonusInput) -> dict[str, Any]:
    rates = {"national": 2000, "provincial": 1000, "school": 300}
    amount = round(value.course_count * rates[value.level], 2)
    return {
        "metric": "course_bonus",
        "amount": amount,
        "level": value.level,
        "formula": "course_count * level_rate",
    }


def _research_performance(value: _ResearchInput) -> dict[str, Any]:
    amount = round(
        value.papers * value.paper_weight
        + value.projects * value.project_weight
        + value.funding * value.funding_rate,
        2,
    )
    return {
        "metric": "research_performance",
        "amount": amount,
        "formula": (
            "papers * paper_weight + projects * project_weight + funding * funding_rate"
        ),
    }


@dataclass(frozen=True)
class RegisteredFunction:
    name: str
    version: str
    description: str
    input_model: type[BaseModel]
    output_schema: dict[str, Any]
    handler: Callable[[Any], dict[str, Any]]

    def metadata(self) -> dict[str, Any]:
        return {
            "kind": "registered",
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_schema,
        }

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = self.input_model.model_validate(input_data)
        except ValidationError as error:
            raise FunctionExecutionError(
                "INVALID_FUNCTION_INPUT",
                "function input did not satisfy its contract",
                {"errors": error.errors()},
            ) from error
        return self.handler(parsed)


_AMOUNT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["metric", "amount", "formula"],
    "properties": {
        "metric": {"type": "string"},
        "amount": {"type": "number"},
        "formula": {"type": "string"},
    },
}

_REGISTRY: dict[tuple[str, str], RegisteredFunction] = {
    ("teaching_performance", "1.0.0"): RegisteredFunction(
        "teaching_performance",
        "1.0.0",
        "Calculate teaching performance from approved workload inputs.",
        _TeachingInput,
        _AMOUNT_OUTPUT_SCHEMA,
        _teaching_performance,
    ),
    ("course_bonus", "1.0.0"): RegisteredFunction(
        "course_bonus",
        "1.0.0",
        "Calculate course-level bonus using the approved level mapping.",
        _CourseBonusInput,
        _AMOUNT_OUTPUT_SCHEMA,
        _course_bonus,
    ),
    ("research_performance", "1.0.0"): RegisteredFunction(
        "research_performance",
        "1.0.0",
        "Calculate research performance from papers, projects, and funding.",
        _ResearchInput,
        _AMOUNT_OUTPUT_SCHEMA,
        _research_performance,
    ),
}


def get_registered_function(name: str, version: str) -> RegisteredFunction:
    function = _REGISTRY.get((name, version))
    if function is None:
        raise FunctionNotFoundError(name, version)
    return function


def list_registered_functions() -> list[RegisteredFunction]:
    return sorted(_REGISTRY.values(), key=lambda item: (item.name, item.version))


def execute_registered_function(
    function_spec: dict[str, Any], input_data: dict[str, Any]
) -> dict[str, Any]:
    if function_spec.get("kind") != "registered":
        raise FunctionExecutionError(
            "INVALID_FUNCTION_SPEC",
            "function kind must be registered",
        )
    name = function_spec.get("name")
    version = function_spec.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise FunctionExecutionError(
            "INVALID_FUNCTION_SPEC",
            "function name and version must be strings",
        )
    return get_registered_function(name, version).execute(input_data)
