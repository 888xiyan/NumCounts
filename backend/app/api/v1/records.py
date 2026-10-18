from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.calculation import CalculationAttempt, CalculationRecord
from app.models.user import User, UserRole
from app.schemas.records import (
    CalculationAttemptListResponse,
    CalculationAttemptResponse,
    CalculationErrorResponse,
    CalculationRecordListResponse,
    CalculationRecordResponse,
    CreateRecordRequest,
    RunPendingRequest,
    RunPendingResponse,
)
from app.services.calculation_service import (
    create_record,
    execute_record,
    get_record,
    list_attempts,
    list_records,
    reload_record,
    retry_record,
    run_pending,
)

router = APIRouter(prefix="/records", tags=["calculation-records"])


def _record_response(record: CalculationRecord) -> CalculationRecordResponse:
    error = None
    if record.error_code is not None:
        error = CalculationErrorResponse(
            code=record.error_code,
            message=record.error_message or "calculation failed",
            details=record.error_details,
        )
    return CalculationRecordResponse(
        id=record.id,
        table_name=record.table_name,
        period_id=record.period_id,
        input=record.input_data,
        function=record.function_spec,
        plugin=record.plugin_snapshot,
        output=record.output_data,
        status=record.status,
        error=error,
        attempt_count=record.attempt_count,
        version=record.lock_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _attempt_response(attempt: CalculationAttempt) -> CalculationAttemptResponse:
    return CalculationAttemptResponse(
        id=attempt.id,
        record_id=attempt.record_id,
        attempt_no=attempt.attempt_no,
        execution_id=attempt.execution_id,
        executor_type=attempt.executor_type,
        status=attempt.status,
        input_snapshot=attempt.input_snapshot,
        function_snapshot=attempt.function_snapshot,
        output_snapshot=attempt.output_snapshot,
        error_snapshot=attempt.error_snapshot,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        duration_ms=attempt.duration_ms,
    )


@router.post(
    "", response_model=CalculationRecordResponse, status_code=status.HTTP_201_CREATED
)
async def create_calculation_record(
    request: CreateRecordRequest,
    response: Response,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordResponse:
    record, created = await create_record(
        session,
        request=request,
        idempotency_key=str(idempotency_key),
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _record_response(record)


@router.get("", response_model=CalculationRecordListResponse)
async def list_calculation_records(
    table_name: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$"),
    status_filter: str | None = Query(
        default=None, alias="status", pattern=r"^(pending|running|success|failed)$"
    ),
    period_id: str | None = Query(default=None, max_length=64),
    function_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordListResponse:
    records = await list_records(
        session,
        table_name=table_name,
        status=status_filter,
        period_id=period_id,
        function_name=function_name,
        limit=limit,
    )
    return CalculationRecordListResponse(
        data=[_record_response(item) for item in records]
    )


@router.post("/run-pending", response_model=RunPendingResponse)
async def run_pending_records(
    request: RunPendingRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RunPendingResponse:
    records, skipped = await run_pending(session, limit=request.limit)
    responses = [_record_response(item) for item in records]
    return RunPendingResponse(
        processed=len(responses),
        succeeded=sum(item.status == "success" for item in responses),
        failed=sum(item.status == "failed" for item in responses),
        skipped=skipped,
        records=responses,
    )


@router.get("/{record_id}", response_model=CalculationRecordResponse)
async def get_calculation_record(
    record_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordResponse:
    return _record_response(await get_record(session, record_id=record_id))


@router.post("/{record_id}/execute", response_model=CalculationRecordResponse)
async def execute_calculation_record(
    record_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordResponse:
    return _record_response(await execute_record(session, record_id=record_id))


@router.post("/{record_id}/reload", response_model=CalculationRecordResponse)
async def reload_calculation_record(
    record_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordResponse:
    return _record_response(await reload_record(session, record_id=record_id))


@router.post("/{record_id}/retry", response_model=CalculationRecordResponse)
async def retry_calculation_record(
    record_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationRecordResponse:
    return _record_response(await retry_record(session, record_id=record_id))


@router.get("/{record_id}/attempts", response_model=CalculationAttemptListResponse)
async def list_calculation_attempts(
    record_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> CalculationAttemptListResponse:
    attempts = await list_attempts(session, record_id=record_id)
    return CalculationAttemptListResponse(
        data=[_attempt_response(attempt) for attempt in attempts]
    )
