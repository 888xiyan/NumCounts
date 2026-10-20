"""Self-service endpoints that never expose another member's performance."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.formal_calculation import (
    FormalCalculationResult,
    FormalCalculationResultSource,
)
from app.models.user import User, UserRole
from app.schemas.formal_calculations import (
    FormalCalculationErrorResponse,
    FormalCalculationResultListResponse,
    FormalCalculationResultResponse,
    FormalCalculationResultSourceResponse,
)
from app.services.audit_service import write_audit_event
from app.services.formal_calculation_service import (
    list_result_sources,
    render_formal_result_csv,
)
from app.services.member_service import (
    list_member_formal_results,
    require_teacher_id,
)

router = APIRouter(prefix="/me", tags=["member-self-service"])


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


@router.get(
    "/formal-calculation-results", response_model=FormalCalculationResultListResponse
)
async def list_my_formal_results(
    period_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> FormalCalculationResultListResponse:
    results = await list_member_formal_results(
        session,
        teacher_id=require_teacher_id(user),
        period_id=period_id,
        limit=limit,
    )
    return FormalCalculationResultListResponse(
        data=[await _result_response(session, result) for result in results]
    )


@router.get("/formal-calculation-results/export", response_class=Response)
async def export_my_formal_results(
    period_id: str = Query(min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> Response:
    teacher_id = require_teacher_id(user)
    results = await list_member_formal_results(
        session,
        teacher_id=teacher_id,
        period_id=period_id,
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
        event_type="MEMBER_FORMAL_RESULTS_EXPORTED",
        resource_type="member_formal_result_export",
        resource_id=export_id,
        details={
            "teacher_id": teacher_id,
            "period_id": period_id,
            "result_count": len(results),
        },
    )
    return Response(
        content=render_formal_result_csv(results, sources_by_result),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="my-formal-results-{period_id}.csv"'
            )
        },
    )
