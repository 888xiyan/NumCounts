import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.errors import APIError
from app.db.session import get_session
from app.models.formal_calculation import (
    FormalCalculationBatch,
    FormalCalculationBatchStatus,
    FormalCalculationResult,
    FormalCalculationResultSource,
    FormalCalculationResultStatus,
)
from app.models.user import User, UserRole
from app.schemas.formal_calculations import (
    CreateFormalCalculationBatchRequest,
    FormalCalculationBatchListResponse,
    FormalCalculationBatchResponse,
    FormalCalculationErrorResponse,
    FormalCalculationResultListResponse,
    FormalCalculationResultResponse,
    FormalCalculationResultSourceResponse,
    ReviewFormalCalculationBatchRequest,
)
from app.services.audit_service import write_audit_event
from app.services.formal_calculation_service import (
    get_formal_calculation_batch,
    list_formal_calculation_batches,
    list_formal_calculation_results,
    list_result_sources,
    render_formal_result_csv,
    review_formal_calculation_batch,
    start_formal_calculation_batch,
)

router = APIRouter(
    prefix="/formal-calculation-batches", tags=["formal-calculation-batches"]
)
result_router = APIRouter(
    prefix="/formal-calculation-results", tags=["formal-calculation-results"]
)


def _error_response(
    *, code: str | None, message: str | None, details: dict[str, Any] | None
) -> FormalCalculationErrorResponse | None:
    if code is None:
        return None
    return FormalCalculationErrorResponse(
        code=code,
        message=message or "formal calculation failed",
        details=details,
    )


def _source_response(
    source: FormalCalculationResultSource,
) -> FormalCalculationResultSourceResponse:
    return FormalCalculationResultSourceResponse(
        id=source.id,
        achievement_id=source.achievement_id,
        achievement=source.achievement_snapshot,
        created_at=source.created_at,
    )


async def _result_response(
    session: AsyncSession, result: FormalCalculationResult
) -> FormalCalculationResultResponse:
    return FormalCalculationResultResponse(
        id=result.id,
        batch_id=result.batch_id,
        teacher_id=result.teacher_id,
        teacher_name=result.teacher_name,
        department_id=result.department_id,
        period_id=result.period_id,
        result_version=result.result_version,
        workflow_run_id=result.workflow_run_id,
        status=result.status,
        total_amount=result.total_amount,
        result=result.result_data,
        error=_error_response(
            code=result.error_code,
            message=result.error_message,
            details=result.error_details,
        ),
        created_at=result.created_at,
        finished_at=result.finished_at,
        sources=[
            _source_response(source)
            for source in await list_result_sources(session, result_id=result.id)
        ],
    )


async def _batch_response(
    session: AsyncSession, batch: FormalCalculationBatch
) -> FormalCalculationBatchResponse:
    results = await list_formal_calculation_results(session, batch_id=batch.id)
    return FormalCalculationBatchResponse(
        id=batch.id,
        period_id=batch.period_id,
        occurred_from=batch.occurred_from,
        occurred_to=batch.occurred_to,
        department_id=batch.department_id,
        teacher_ids=batch.teacher_ids,
        workflow=batch.workflow_snapshot,
        input_mappings=batch.input_mappings,
        result_node_key=batch.result_node_key,
        status=batch.status,
        created_by_user_id=batch.created_by_user_id,
        reviewed_by_user_id=batch.reviewed_by_user_id,
        reviewed_at=batch.reviewed_at,
        error=_error_response(
            code=batch.error_code,
            message=batch.error_message,
            details=batch.error_details,
        ),
        created_at=batch.created_at,
        finished_at=batch.finished_at,
        results=[await _result_response(session, result) for result in results],
    )


@router.post(
    "",
    response_model=FormalCalculationBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_batch(
    request: CreateFormalCalculationBatchRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> FormalCalculationBatchResponse:
    batch = await start_formal_calculation_batch(session, request=request, user=user)
    return await _batch_response(session, batch)


@router.get("", response_model=FormalCalculationBatchListResponse)
async def list_batches(
    period_id: str | None = Query(default=None, max_length=64),
    status_filter: FormalCalculationBatchStatus | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> FormalCalculationBatchListResponse:
    batches = await list_formal_calculation_batches(
        session, period_id=period_id, status=status_filter, limit=limit
    )
    return FormalCalculationBatchListResponse(
        data=[await _batch_response(session, batch) for batch in batches]
    )


@router.get("/{batch_id}", response_model=FormalCalculationBatchResponse)
async def get_batch(
    batch_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> FormalCalculationBatchResponse:
    return await _batch_response(
        session, await get_formal_calculation_batch(session, batch_id=batch_id)
    )


@router.post("/{batch_id}/review", response_model=FormalCalculationBatchResponse)
async def review_batch(
    batch_id: str,
    _: ReviewFormalCalculationBatchRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> FormalCalculationBatchResponse:
    batch = await review_formal_calculation_batch(session, batch_id=batch_id, user=user)
    return await _batch_response(session, batch)


@result_router.get("", response_model=FormalCalculationResultListResponse)
async def list_results(
    batch_id: str | None = Query(default=None, min_length=36, max_length=36),
    period_id: str | None = Query(default=None, max_length=64),
    teacher_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> FormalCalculationResultListResponse:
    results = await list_formal_calculation_results(
        session,
        batch_id=batch_id,
        period_id=period_id,
        teacher_id=teacher_id,
        limit=limit,
    )
    return FormalCalculationResultListResponse(
        data=[await _result_response(session, result) for result in results]
    )


@result_router.get("/export", response_class=Response)
async def export_results(
    batch_id: str | None = Query(default=None, min_length=36, max_length=36),
    period_id: str | None = Query(default=None, max_length=64),
    teacher_id: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> Response:
    if batch_id is None and period_id is None:
        raise APIError(
            status_code=422,
            code="FORMAL_EXPORT_SCOPE_REQUIRED",
            message="batch_id or period_id is required for formal result export",
        )
    results = await list_formal_calculation_results(
        session,
        batch_id=batch_id,
        period_id=period_id,
        teacher_id=teacher_id,
        status=FormalCalculationResultStatus.SUCCESS,
        limit=10_000,
    )
    sources_by_result = {
        result.id: await list_result_sources(session, result_id=result.id)
        for result in results
    }
    export_id = str(uuid.uuid4())
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="FORMAL_CALCULATION_RESULTS_EXPORTED",
        resource_type="formal_calculation_export",
        resource_id=export_id,
        details={
            "batch_id": batch_id,
            "period_id": period_id,
            "teacher_id": teacher_id,
            "result_count": len(results),
        },
    )
    filename_scope = batch_id or period_id or "results"
    content_disposition = (
        f'attachment; filename="formal-results-{filename_scope}.csv"'
    )
    return Response(
        content=render_formal_result_csv(results, sources_by_result),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": content_disposition},
    )
