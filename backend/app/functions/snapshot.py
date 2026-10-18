"""Immutable, verifiable function-body snapshots for formal calculations."""

import hashlib
import hmac
import inspect
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from app.executors.registry import get_executor, get_function_artifact
from app.functions.registry import FunctionExecutionError, get_registered_function

_SNAPSHOT_SCHEMA_VERSION = "numcounts.function-body.v1"


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_of(value: Any, *, label: str) -> str:
    try:
        return inspect.getsource(value).strip()
    except (OSError, TypeError) as error:
        raise FunctionExecutionError(
            "FUNCTION_SNAPSHOT_UNAVAILABLE",
            "function source cannot be captured for formal execution",
            {"component": label},
        ) from error


def _runtime_dependencies() -> dict[str, str]:
    try:
        pydantic_version = version("pydantic")
    except PackageNotFoundError:  # pragma: no cover - application requires it.
        pydantic_version = "unavailable"
    return {"pydantic": pydantic_version}


def _with_digest(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "content_sha256": _digest(payload)}


def _registered_snapshot(function_spec: dict[str, Any]) -> dict[str, Any]:
    name = function_spec.get("name")
    version_value = function_spec.get("version")
    if not isinstance(name, str) or not isinstance(version_value, str):
        raise FunctionExecutionError(
            "INVALID_FUNCTION_SPEC", "registered function reference is malformed"
        )
    registered = get_registered_function(name, version_value)
    handler = registered.handler
    input_model = registered.input_model
    return _with_digest(
        {
            "schema_version": _SNAPSHOT_SCHEMA_VERSION,
            "kind": "registered_python",
            "function": {
                "kind": "registered",
                "name": registered.name,
                "version": registered.version,
            },
            "body": {
                "language": "python",
                "module": handler.__module__,
                "qualname": handler.__qualname__,
                "source": _source_of(handler, label="registered function handler"),
            },
            "input_contract": {
                "model_module": input_model.__module__,
                "model_qualname": input_model.__qualname__,
                "model_source": _source_of(input_model, label="registered input model"),
                "json_schema": input_model.model_json_schema(),
            },
            "output_schema": registered.output_schema,
            "runtime": {
                "python_implementation": platform.python_implementation(),
                "python_version": platform.python_version(),
                "dependencies": _runtime_dependencies(),
            },
        }
    )


def _external_snapshot(function_spec: dict[str, Any]) -> dict[str, Any]:
    executor_id = function_spec.get("executor_id")
    name = function_spec.get("name")
    version_value = function_spec.get("version")
    if not all(isinstance(item, str) for item in (executor_id, name, version_value)):
        raise FunctionExecutionError(
            "INVALID_FUNCTION_SPEC", "external function reference is malformed"
        )
    executor = get_executor(executor_id)
    artifact = get_function_artifact(
        executor_id, name=name, version=version_value, executor=executor
    )
    return _with_digest(
        {
            "schema_version": _SNAPSHOT_SCHEMA_VERSION,
            "kind": "external_source_bundle",
            "function": {
                "kind": "external",
                "executor_id": executor_id,
                "name": name,
                "version": version_value,
            },
            "body": {
                "language": artifact.language,
                "source": artifact.source,
                "source_sha256": artifact.source_sha256,
            },
            "dependencies": artifact.dependencies,
            "executor_contract": {
                "execution_path": executor.execution_path,
                "timeout_ms": executor.timeout_ms,
            },
        }
    )


def build_function_body_snapshot(function_spec: dict[str, Any]) -> dict[str, Any]:
    """Capture the exact approved implementation selected for an attempt."""
    kind = function_spec.get("kind")
    if kind == "registered":
        return _registered_snapshot(function_spec)
    if kind == "external":
        return _external_snapshot(function_spec)
    raise FunctionExecutionError(
        "INVALID_FUNCTION_SPEC",
        "function body snapshots require a registered or external function",
    )


def verify_function_body_snapshot(snapshot: dict[str, Any] | None) -> bool | None:
    """Return integrity status; ``None`` identifies legacy reference-only history."""
    if snapshot is None:
        return None
    digest = snapshot.get("content_sha256")
    if not isinstance(digest, str):
        return False
    payload = {key: value for key, value in snapshot.items() if key != "content_sha256"}
    return (
        payload.get("schema_version") == _SNAPSHOT_SCHEMA_VERSION
        and hmac.compare_digest(digest, _digest(payload))
    )
