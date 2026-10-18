"""Strict HTTP client for trusted external performance executors."""

from typing import Any

import httpx

from app.core.config import ExternalExecutorSettings
from app.executors.registry import get_executor
from app.functions.registry import FunctionExecutionError


def _invalid_response(message: str, details: dict[str, Any] | None = None) -> None:
    raise FunctionExecutionError("EXECUTOR_INVALID_RESPONSE", message, details)


async def execute_external_function(
    *,
    executor_id: str,
    execution_id: str,
    record_id: str,
    table_name: str,
    function: dict[str, str],
    input_data: dict[str, Any],
    executor: ExternalExecutorSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Execute one fixed executor endpoint and convert outcomes to domain errors."""
    config = executor or get_executor(executor_id)
    headers = {"X-Execution-Id": execution_id}
    if config.authorization_token:
        headers["Authorization"] = f"Bearer {config.authorization_token}"
    payload = {
        "execution_id": execution_id,
        "record_id": record_id,
        "table_name": table_name,
        "function": function,
        "input": input_data,
        "timeout_ms": config.timeout_ms,
    }
    try:
        async with httpx.AsyncClient(
            timeout=config.timeout_ms / 1000,
            transport=transport,
        ) as client:
            response = await client.post(
                f"{config.base_url}{config.execution_path}",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as error:
        raise FunctionExecutionError(
            "EXECUTOR_TIMEOUT",
            "external executor timed out",
            {"executor_id": executor_id},
        ) from error
    except httpx.HTTPError as error:
        raise FunctionExecutionError(
            "EXECUTOR_CONNECTION_ERROR",
            "external executor connection failed",
            {"executor_id": executor_id},
        ) from error

    if response.status_code in {401, 403}:
        raise FunctionExecutionError(
            "EXECUTOR_AUTH_FAILED",
            "external executor rejected service authentication",
            {"executor_id": executor_id, "status_code": response.status_code},
        )
    if response.status_code >= 500:
        raise FunctionExecutionError(
            "EXECUTOR_UNAVAILABLE",
            "external executor is unavailable",
            {"executor_id": executor_id, "status_code": response.status_code},
        )
    if response.status_code < 200 or response.status_code >= 300:
        _invalid_response(
            "external executor returned an unexpected HTTP status",
            {"executor_id": executor_id, "status_code": response.status_code},
        )
    try:
        body = response.json()
    except ValueError as error:
        raise FunctionExecutionError(
            "EXECUTOR_INVALID_RESPONSE",
            "external executor returned non-JSON content",
            {"executor_id": executor_id},
        ) from error
    if not isinstance(body, dict):
        _invalid_response("external executor response must be a JSON object")
    response_status = body.get("status")
    if response_status == "success":
        output = body.get("output")
        if not isinstance(output, dict):
            _invalid_response("successful executor response requires object output")
        return output
    if response_status == "failed":
        error = body.get("error")
        if not isinstance(error, dict):
            _invalid_response("failed executor response requires an error object")
        code = error.get("code")
        message = error.get("message")
        if not isinstance(code, str) or not isinstance(message, str):
            _invalid_response("executor error requires string code and message")
        details = error.get("details")
        if details is not None and not isinstance(details, dict):
            _invalid_response("executor error details must be an object")
        raise FunctionExecutionError(code, message, details)
    _invalid_response("executor response status must be success or failed")
