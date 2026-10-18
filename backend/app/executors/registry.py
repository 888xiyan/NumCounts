"""Resolve executor IDs from deployment configuration, never record content."""

from app.core.config import (
    ExternalExecutorSettings,
    ExternalFunctionArtifact,
    settings,
)
from app.functions.registry import FunctionExecutionError


class ExternalExecutorNotFoundError(FunctionExecutionError):
    def __init__(self, executor_id: str):
        super().__init__(
            "EXECUTOR_NOT_FOUND",
            "external executor was not found",
            {"executor_id": executor_id},
        )


def get_executor(
    executor_id: str,
    *,
    configured_executors: list[ExternalExecutorSettings] | None = None,
) -> ExternalExecutorSettings:
    executors = (
        configured_executors
        if configured_executors is not None
        else settings.external_executors
    )
    matching = [item for item in executors if item.executor_id == executor_id]
    if len(matching) != 1:
        raise ExternalExecutorNotFoundError(executor_id)
    return matching[0]


def get_function_artifact(
    executor_id: str,
    *,
    name: str,
    version: str,
    executor: ExternalExecutorSettings | None = None,
) -> ExternalFunctionArtifact:
    """Resolve an externally audited function source bundle by stable version."""
    resolved_executor = executor or get_executor(executor_id)
    matching = [
        artifact
        for artifact in resolved_executor.function_artifacts
        if artifact.name == name and artifact.version == version
    ]
    if len(matching) != 1:
        raise FunctionExecutionError(
            "FUNCTION_SNAPSHOT_UNAVAILABLE",
            "external function has no configured source artifact for formal execution",
            {
                "executor_id": executor_id,
                "name": name,
                "version": version,
            },
        )
    return matching[0]
