"""Resolve executor IDs from deployment configuration, never record content."""

from app.core.config import ExternalExecutorSettings, settings
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
