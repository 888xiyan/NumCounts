"""Stateful calculation-record service for the formal single-worker kernel."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.executors import execute_external_function, get_executor
from app.functions import (
    FunctionExecutionError,
    execute_registered_function,
    get_registered_function,
)
from app.models.calculation import CalculationAttempt, CalculationRecord
from app.schemas.records import (
    CreateRecordRequest,
    ExternalFunctionSpec,
    PluginFunctionSpec,
    RegisteredFunctionSpec,
)
from app.services.link_service import (
    invalidate_downstream_records,
    resolve_linked_input,
)
from app.services.plugin_service import resolve_enabled_plugin_snapshot

_MAX_JSON_BYTES = 64 * 1024
_EXECUTABLE_STATUSES = {"pending", "waiting", "success", "failed"}
_execution_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_json_size(value: dict[str, Any], *, field_name: str) -> None:
    size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    if size > _MAX_JSON_BYTES:
        raise APIError(
            status_code=422,
            code="INPUT_TOO_LARGE",
            message=f"{field_name} cannot exceed 64 KiB",
            details={"field": field_name, "max_bytes": _MAX_JSON_BYTES},
        )


def _record_matches_request(
    record: CalculationRecord,
    *,
    table_name: str,
    period_id: str | None,
    input_data: dict[str, Any],
    function_spec: dict[str, Any],
    plugin_snapshot: dict[str, Any] | None,
) -> bool:
    return (
        record.table_name == table_name
        and record.period_id == period_id
        and record.input_data == input_data
        and record.function_spec == function_spec
        and record.plugin_snapshot == plugin_snapshot
    )


def _validate_executable_function(function_spec: dict[str, Any]) -> None:
    try:
        kind = function_spec.get("kind")
        if kind == "registered":
            get_registered_function(function_spec["name"], function_spec["version"])
        elif kind == "external":
            get_executor(function_spec["executor_id"])
        else:
            raise FunctionExecutionError(
                "INVALID_FUNCTION_SPEC",
                "function kind must be registered or external",
            )
    except (KeyError, TypeError) as error:
        raise FunctionExecutionError(
            "INVALID_FUNCTION_SPEC", "function reference is malformed"
        ) from error


def _effective_function_spec(record: CalculationRecord) -> dict[str, Any]:
    if record.function_spec.get("kind") != "plugin":
        return record.function_spec
    snapshot = record.plugin_snapshot
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("function"), dict):
        raise FunctionExecutionError(
            "INVALID_PLUGIN_SNAPSHOT",
            "plugin calculation record has no executable function snapshot",
        )
    return snapshot["function"]


def _attempt_function_snapshot(
    record: CalculationRecord, effective_function: dict[str, Any]
) -> dict[str, Any]:
    if record.plugin_snapshot is None:
        return effective_function
    return {
        "function": record.function_spec,
        "resolved_function": effective_function,
        "plugin": record.plugin_snapshot,
    }


async def create_record(
    session: AsyncSession,
    *,
    request: CreateRecordRequest,
    idempotency_key: str,
) -> tuple[CalculationRecord, bool]:
    """Create a pending record, or return the prior result for the same request."""
    input_data = request.input
    function_spec = request.function.model_dump()
    plugin_snapshot: dict[str, Any] | None = None
    try:
        if isinstance(request.function, RegisteredFunctionSpec):
            get_registered_function(request.function.name, request.function.version)
        elif isinstance(request.function, ExternalFunctionSpec):
            get_executor(request.function.executor_id)
        elif isinstance(request.function, PluginFunctionSpec):
            plugin_snapshot = await resolve_enabled_plugin_snapshot(
                session, plugin_id=request.function.plugin_id
            )
            input_data = {**plugin_snapshot["input_defaults"], **request.input}
        else:
            raise FunctionExecutionError(
                "INVALID_FUNCTION_SPEC", "unsupported function kind"
            )
    except FunctionExecutionError as error:
        raise APIError(
            status_code=(
                404
                if error.code in {"FUNCTION_NOT_FOUND", "EXECUTOR_NOT_FOUND"}
                else 422
            ),
            code=error.code,
            message=error.message,
            details=error.details,
        ) from error
    _ensure_json_size(input_data, field_name="input")

    existing = await session.scalar(
        select(CalculationRecord).where(
            CalculationRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if _record_matches_request(
            existing,
            table_name=request.table_name,
            period_id=request.period_id,
            input_data=input_data,
            function_spec=function_spec,
            plugin_snapshot=plugin_snapshot,
        ):
            return existing, False
        raise APIError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message="idempotency key was already used with a different request",
        )

    now = _now()
    record = CalculationRecord(
        table_name=request.table_name,
        period_id=request.period_id,
        idempotency_key=idempotency_key,
        input_data=input_data,
        function_spec=function_spec,
        plugin_id=(plugin_snapshot or {}).get("id"),
        plugin_snapshot=plugin_snapshot,
        status="pending",
        attempt_count=0,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        existing = await session.scalar(
            select(CalculationRecord).where(
                CalculationRecord.idempotency_key == idempotency_key
            )
        )
        if existing is not None and _record_matches_request(
            existing,
            table_name=request.table_name,
            period_id=request.period_id,
            input_data=input_data,
            function_spec=function_spec,
            plugin_snapshot=plugin_snapshot,
        ):
            return existing, False
        raise APIError(
            status_code=409,
            code="IDEMPOTENCY_KEY_REUSED",
            message="idempotency key was already used with a different request",
        ) from error
    await session.refresh(record)
    return record, True


async def create_record_from_plugin_snapshot(
    session: AsyncSession,
    *,
    table_name: str,
    period_id: str | None,
    input_data: dict[str, Any],
    plugin_snapshot: dict[str, Any],
) -> CalculationRecord:
    """Create a workflow record from the plugin version frozen in its node.

    Workflow definitions are immutable.  A later plugin disable therefore must
    not make a historical workflow version ambiguous or silently switch it to a
    different rule.  This trusted internal path never accepts a snapshot from
    the public API.
    """
    _ensure_json_size(input_data, field_name="input")
    plugin_id = plugin_snapshot.get("id")
    effective_function = plugin_snapshot.get("function")
    if not isinstance(plugin_id, str) or not isinstance(effective_function, dict):
        raise APIError(
            status_code=409,
            code="INVALID_PLUGIN_SNAPSHOT",
            message="workflow node has an invalid plugin snapshot",
        )
    try:
        _validate_executable_function(effective_function)
    except FunctionExecutionError as error:
        raise APIError(
            status_code=409,
            code=error.code,
            message=error.message,
            details=error.details,
        ) from error
    now = _now()
    record = CalculationRecord(
        table_name=table_name,
        period_id=period_id,
        input_data=input_data,
        function_spec={"kind": "plugin", "plugin_id": plugin_id},
        plugin_id=plugin_id,
        plugin_snapshot=plugin_snapshot,
        status="pending",
        attempt_count=0,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_record(session: AsyncSession, *, record_id: str) -> CalculationRecord:
    record = await session.get(CalculationRecord, record_id)
    if record is None:
        raise APIError(
            status_code=404,
            code="CALCULATION_RECORD_NOT_FOUND",
            message="calculation record was not found",
        )
    return record


async def list_records(
    session: AsyncSession,
    *,
    table_name: str | None = None,
    status: str | None = None,
    period_id: str | None = None,
    function_name: str | None = None,
    limit: int = 100,
) -> list[CalculationRecord]:
    statement = select(CalculationRecord)
    if table_name is not None:
        statement = statement.where(CalculationRecord.table_name == table_name)
    if status is not None:
        statement = statement.where(CalculationRecord.status == status)
    if period_id is not None:
        statement = statement.where(CalculationRecord.period_id == period_id)
    if function_name is not None:
        statement = statement.where(
            func.json_unquote(
                func.json_extract(CalculationRecord.function_spec, "$.name")
            )
            == function_name
        )
    statement = statement.order_by(CalculationRecord.created_at, CalculationRecord.id)
    return list((await session.scalars(statement.limit(limit))).all())


async def list_attempts(
    session: AsyncSession, *, record_id: str
) -> list[CalculationAttempt]:
    await get_record(session, record_id=record_id)
    statement = (
        select(CalculationAttempt)
        .where(CalculationAttempt.record_id == record_id)
        .order_by(CalculationAttempt.attempt_no)
    )
    return list((await session.scalars(statement)).all())


async def _start_execution(
    session: AsyncSession, *, record_id: str
) -> tuple[CalculationRecord, str | None, dict[str, Any] | None]:
    result = await session.execute(
        select(CalculationRecord)
        .where(CalculationRecord.id == record_id)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise APIError(
            status_code=404,
            code="CALCULATION_RECORD_NOT_FOUND",
            message="calculation record was not found",
        )
    if record.status == "running":
        raise APIError(
            status_code=409,
            code="CALCULATION_ALREADY_RUNNING",
            message="calculation record is already running",
            retryable=True,
        )
    if record.status not in _EXECUTABLE_STATUSES:
        raise APIError(
            status_code=409,
            code="INVALID_CALCULATION_STATE",
            message="calculation record cannot be executed from its current state",
            details={"status": record.status},
        )

    try:
        link_resolution = await resolve_linked_input(session, record=record)
    except FunctionExecutionError as error:
        record.status = "failed"
        record.error_code = error.code
        record.error_message = error.message
        record.error_details = error.details or None
        record.lock_version += 1
        record.updated_at = _now()
        await session.commit()
        await session.refresh(record)
        return record, None, None
    if link_resolution.waiting:
        record.status = "waiting"
        record.updated_at = _now()
        record.lock_version += 1
        await session.commit()
        await session.refresh(record)
        return record, None, None

    effective_function = _effective_function_spec(record)
    now = _now()
    execution_id = str(uuid.uuid4())
    record.status = "running"
    record.output_data = None
    record.error_code = None
    record.error_message = None
    record.error_details = None
    record.attempt_count += 1
    record.lock_version += 1
    record.updated_at = now
    session.add(
        CalculationAttempt(
            record_id=record.id,
            attempt_no=record.attempt_count,
            execution_id=execution_id,
            executor_type=(
                "python_registry"
                if effective_function.get("kind") == "registered"
                else "external_http"
            ),
            status="running",
            input_snapshot=link_resolution.input_data,
            function_snapshot=_attempt_function_snapshot(record, effective_function),
            link_snapshot=link_resolution.snapshots or None,
            started_at=now,
        )
    )
    await session.commit()
    return record, execution_id, link_resolution.input_data


async def _finish_execution(
    session: AsyncSession,
    *,
    record_id: str,
    execution_id: str,
    output: dict[str, Any] | None,
    error: FunctionExecutionError | None,
    started_monotonic: float,
) -> CalculationRecord:
    result = await session.execute(
        select(CalculationRecord)
        .where(CalculationRecord.id == record_id)
        .with_for_update()
    )
    record = result.scalar_one()
    attempt = await session.scalar(
        select(CalculationAttempt)
        .where(CalculationAttempt.execution_id == execution_id)
        .with_for_update()
    )
    if attempt is None:
        raise RuntimeError("calculation attempt disappeared before finalization")

    now = _now()
    duration_ms = max(0, round((time.monotonic() - started_monotonic) * 1000))
    attempt.finished_at = now
    attempt.duration_ms = duration_ms
    record.updated_at = now
    record.lock_version += 1
    if error is None:
        record.status = "success"
        record.output_data = output
        attempt.status = "success"
        attempt.output_snapshot = output
        await invalidate_downstream_records(session, target_record_id=record.id)
    else:
        error_snapshot = {
            "code": error.code,
            "message": error.message,
            "details": error.details or None,
        }
        record.status = "failed"
        record.error_code = error.code
        record.error_message = error.message
        record.error_details = error.details or None
        attempt.status = "failed"
        attempt.error_snapshot = error_snapshot
    await session.commit()
    await session.refresh(record)
    return record


async def _execute_record(
    session: AsyncSession, *, record_id: str
) -> CalculationRecord:
    record, execution_id, execution_input = await _start_execution(
        session, record_id=record_id
    )
    if execution_id is None or execution_input is None:
        return record
    started_monotonic = time.monotonic()
    output: dict[str, Any] | None = None
    execution_error: FunctionExecutionError | None = None
    try:
        effective_function = _effective_function_spec(record)
        if effective_function.get("kind") == "registered":
            output = execute_registered_function(effective_function, execution_input)
        elif effective_function.get("kind") == "external":
            executor_id = effective_function.get("executor_id")
            name = effective_function.get("name")
            version = effective_function.get("version")
            if not all(isinstance(item, str) for item in (executor_id, name, version)):
                raise FunctionExecutionError(
                    "INVALID_FUNCTION_SPEC",
                    "external function requires executor_id, name, and version",
                )
            output = await execute_external_function(
                executor_id=executor_id,
                execution_id=execution_id,
                record_id=record.id,
                table_name=record.table_name,
                function={"name": name, "version": version},
                input_data=execution_input,
            )
        else:
            raise FunctionExecutionError(
                "INVALID_FUNCTION_SPEC", "function kind must be registered or external"
            )
        _ensure_json_size(output, field_name="output")
    except FunctionExecutionError as error:
        execution_error = error
    except Exception:  # Keep unexpected implementation details out of the API.
        execution_error = FunctionExecutionError(
            "FUNCTION_EXECUTION_ERROR", "registered function execution failed"
        )
    return await _finish_execution(
        session,
        record_id=record_id,
        execution_id=execution_id,
        output=output,
        error=execution_error,
        started_monotonic=started_monotonic,
    )


async def execute_record(session: AsyncSession, *, record_id: str) -> CalculationRecord:
    """Execute one record under the MVP process-wide single-worker lock."""
    async with _execution_lock:
        return await _execute_record(session, record_id=record_id)


async def _reload_record(session: AsyncSession, *, record_id: str) -> CalculationRecord:
    result = await session.execute(
        select(CalculationRecord)
        .where(CalculationRecord.id == record_id)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise APIError(
            status_code=404,
            code="CALCULATION_RECORD_NOT_FOUND",
            message="calculation record was not found",
        )
    if record.status == "running":
        raise APIError(
            status_code=409,
            code="CALCULATION_ALREADY_RUNNING",
            message="running calculation records cannot be reloaded",
            retryable=True,
        )
    record.status = "pending"
    record.output_data = None
    record.error_code = None
    record.error_message = None
    record.error_details = None
    record.lock_version += 1
    record.updated_at = _now()
    await invalidate_downstream_records(session, target_record_id=record.id)
    await session.commit()
    await session.refresh(record)
    return record


async def reload_record(session: AsyncSession, *, record_id: str) -> CalculationRecord:
    async with _execution_lock:
        return await _reload_record(session, record_id=record_id)


async def retry_record(session: AsyncSession, *, record_id: str) -> CalculationRecord:
    """Locally reload then execute one record, preserving historical attempts."""
    async with _execution_lock:
        await _reload_record(session, record_id=record_id)
        return await _execute_record(session, record_id=record_id)


async def run_pending(
    session: AsyncSession, *, limit: int
) -> tuple[list[CalculationRecord], int]:
    """Run a bounded FIFO batch.  A running record skipped by a peer is harmless."""
    statement = (
        select(CalculationRecord.id)
        .where(CalculationRecord.status.in_(("pending", "waiting")))
        .order_by(CalculationRecord.created_at, CalculationRecord.id)
        .limit(limit)
    )
    record_ids = list((await session.scalars(statement)).all())
    records: list[CalculationRecord] = []
    skipped = 0
    for record_id in record_ids:
        try:
            records.append(await execute_record(session, record_id=record_id))
        except APIError as error:
            if error.detail.get("code") == "CALCULATION_ALREADY_RUNNING":
                skipped += 1
                continue
            raise
    return records, skipped


async def recover_interrupted_records(
    session: AsyncSession,
) -> list[CalculationRecord]:
    """Make records left running by a process crash explicitly retryable."""
    result = await session.execute(
        select(CalculationRecord)
        .where(CalculationRecord.status == "running")
        .with_for_update()
    )
    records = list(result.scalars().all())
    if not records:
        return []
    now = _now()
    for record in records:
        record.status = "failed"
        record.error_code = "EXECUTION_INTERRUPTED"
        record.error_message = "execution was interrupted before completion"
        record.error_details = {"recovery": "manual"}
        record.lock_version += 1
        record.updated_at = now
        attempt = await session.scalar(
            select(CalculationAttempt)
            .where(
                CalculationAttempt.record_id == record.id,
                CalculationAttempt.status == "running",
            )
            .with_for_update()
        )
        if attempt is not None:
            attempt.status = "failed"
            attempt.error_snapshot = {
                "code": "EXECUTION_INTERRUPTED",
                "message": "execution was interrupted before completion",
            }
            attempt.finished_at = now
            attempt.duration_ms = None
    await session.commit()
    for record in records:
        await session.refresh(record)
    return records
