"""Member submission and administrator review for special cases."""

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.errors import APIError
from app.db.session import get_session
from app.models.special_performance import (
    SpecialPerformanceCase,
    SpecialPerformanceCaseEvent,
    SpecialPerformanceCaseMaterial,
    SpecialPerformanceCaseStatus,
)
from app.models.user import User, UserRole
from app.schemas.special_performance import (
    AdjustSpecialPerformanceDeadlineRequest,
    CreateSpecialPerformanceCaseRequest,
    HandleSpecialPerformanceCaseRequest,
    ReviewSpecialPerformanceCaseRequest,
    SpecialPerformanceCaseEventResponse,
    SpecialPerformanceCaseListResponse,
    SpecialPerformanceCaseMaterialResponse,
    SpecialPerformanceCaseResponse,
    UpdateSpecialPerformanceCaseRequest,
)
from app.services.special_performance_service import (
    MATERIAL_MAX_BYTES,
    add_case_material,
    adjust_special_case_deadline,
    case_events,
    create_special_case,
    current_case_materials,
    get_special_case,
    handle_special_case,
    list_special_cases,
    load_case_material,
    process_approved_special_case,
    remove_case_material,
    review_special_case,
    submit_special_case,
    update_special_case,
)

router = APIRouter(
    prefix="/special-performance-cases", tags=["special-performance-cases"]
)


def _material_response(
    material: SpecialPerformanceCaseMaterial,
) -> SpecialPerformanceCaseMaterialResponse:
    return SpecialPerformanceCaseMaterialResponse(
        id=material.id,
        material_key=material.material_key,
        version=material.version,
        filename=material.filename,
        media_type=material.media_type,
        sha256=material.sha256,
        size_bytes=material.size_bytes,
        is_current=material.is_current,
        created_at=material.created_at,
    )


def _event_response(
    event: SpecialPerformanceCaseEvent,
) -> SpecialPerformanceCaseEventResponse:
    return SpecialPerformanceCaseEventResponse(
        id=event.id,
        event_type=event.event_type,
        from_status=event.from_status,
        to_status=event.to_status,
        actor_user_id=event.actor_user_id,
        details=event.details,
        created_at=event.created_at,
    )


async def _case_response(
    session: AsyncSession, case: SpecialPerformanceCase
) -> SpecialPerformanceCaseResponse:
    now = datetime.now(UTC)
    review_due_at = case.review_due_at
    if review_due_at is not None and review_due_at.tzinfo is None:
        review_due_at = review_due_at.replace(tzinfo=UTC)
    return SpecialPerformanceCaseResponse(
        id=case.id,
        case_type=case.case_type,
        status=case.status,
        submitted_by_user_id=case.submitted_by_user_id,
        teacher_id=case.teacher_id,
        teacher_name=case.teacher_name,
        department_id=case.department_id,
        period_id=case.period_id,
        original_result_id=case.original_result_id,
        title=case.title,
        form_data=case.form_data,
        submitted_snapshot=case.submitted_snapshot,
        submission_version=case.submission_version,
        submitted_at=case.submitted_at,
        review_due_at=review_due_at,
        overdue=(
            review_due_at is not None
            and review_due_at < now
            and case.status
            in {
                SpecialPerformanceCaseStatus.SUBMITTED,
                SpecialPerformanceCaseStatus.REVIEWING,
            }
        ),
        processed_by_user_id=case.processed_by_user_id,
        reviewed_by_user_id=case.reviewed_by_user_id,
        processing_comment=case.processing_comment,
        review_comment=case.review_comment,
        plugin_id=case.plugin_id,
        plugin_snapshot=case.plugin_snapshot,
        plugin_execution_status=case.plugin_execution_status,
        calculation_record_id=case.calculation_record_id,
        achievement_id=case.achievement_id,
        processing_error=case.processing_error,
        materials=[
            _material_response(material)
            for material in await current_case_materials(session, case_id=case.id)
        ],
        events=[
            _event_response(event)
            for event in await case_events(session, case_id=case.id)
        ],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@router.post(
    "",
    response_model=SpecialPerformanceCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_case(
    request: CreateSpecialPerformanceCaseRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseResponse:
    case = await create_special_case(session, user=user, request=request)
    return await _case_response(session, case)


@router.get("/mine", response_model=SpecialPerformanceCaseListResponse)
async def list_my_cases(
    status_filter: SpecialPerformanceCaseStatus | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseListResponse:
    cases = await list_special_cases(
        session, user=user, status=status_filter, limit=limit
    )
    return SpecialPerformanceCaseListResponse(
        data=[await _case_response(session, case) for case in cases]
    )


@router.get("", response_model=SpecialPerformanceCaseListResponse)
async def list_admin_cases(
    status_filter: SpecialPerformanceCaseStatus | None = Query(
        default=None, alias="status"
    ),
    overdue_only: bool = False,
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> SpecialPerformanceCaseListResponse:
    cases = await list_special_cases(
        session,
        user=user,
        status=status_filter,
        overdue_only=overdue_only,
        limit=limit,
    )
    return SpecialPerformanceCaseListResponse(
        data=[await _case_response(session, case) for case in cases]
    )


@router.get("/{case_id}", response_model=SpecialPerformanceCaseResponse)
async def get_case(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER, UserRole.ADMIN)),
) -> SpecialPerformanceCaseResponse:
    case = await get_special_case(session, case_id=case_id, user=user)
    return await _case_response(session, case)


@router.patch("/{case_id}", response_model=SpecialPerformanceCaseResponse)
async def patch_case(
    case_id: str,
    request: UpdateSpecialPerformanceCaseRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseResponse:
    case = await update_special_case(
        session, case_id=case_id, user=user, request=request
    )
    return await _case_response(session, case)


@router.post("/{case_id}/submit", response_model=SpecialPerformanceCaseResponse)
async def submit_case(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseResponse:
    case = await submit_special_case(session, case_id=case_id, user=user)
    return await _case_response(session, case)


@router.post(
    "/{case_id}/materials/{material_key}",
    response_model=SpecialPerformanceCaseMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    case_id: str,
    material_key: str,
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    content_type: str = Header(
        default="application/octet-stream", alias="Content-Type"
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseMaterialResponse:
    content_buffer = bytearray()
    async for chunk in request.stream():
        if len(content_buffer) + len(chunk) > MATERIAL_MAX_BYTES:
            raise APIError(
                status_code=413,
                code="MATERIAL_SIZE_INVALID",
                message="material content cannot exceed 10 MiB",
            )
        content_buffer.extend(chunk)
    material = await add_case_material(
        session,
        case_id=case_id,
        material_key=material_key,
        filename=filename,
        media_type=content_type,
        content=bytes(content_buffer),
        user=user,
    )
    return _material_response(material)


@router.get(
    "/{case_id}/materials", response_model=list[SpecialPerformanceCaseMaterialResponse]
)
async def get_case_materials(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER, UserRole.ADMIN)),
) -> list[SpecialPerformanceCaseMaterialResponse]:
    await get_special_case(session, case_id=case_id, user=user)
    materials = await current_case_materials(session, case_id=case_id)
    return [_material_response(material) for material in materials]


@router.delete(
    "/{case_id}/materials/{material_id}",
    response_model=SpecialPerformanceCaseMaterialResponse,
)
async def delete_case_material(
    case_id: str,
    material_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER)),
) -> SpecialPerformanceCaseMaterialResponse:
    material = await remove_case_material(
        session, case_id=case_id, material_id=material_id, user=user
    )
    return _material_response(material)


@router.get("/{case_id}/materials/{material_id}/content", response_class=Response)
async def download_case_material(
    case_id: str,
    material_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.USER, UserRole.ADMIN)),
) -> Response:
    _, material = await load_case_material(
        session, case_id=case_id, material_id=material_id, user=user
    )
    return Response(
        content=material.content,
        media_type=material.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(material.filename)}"
            ),
            "ETag": f'"{material.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{case_id}/handle", response_model=SpecialPerformanceCaseResponse)
async def handle_case(
    case_id: str,
    request: HandleSpecialPerformanceCaseRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> SpecialPerformanceCaseResponse:
    case = await handle_special_case(
        session, case_id=case_id, user=user, request=request
    )
    return await _case_response(session, case)


@router.post("/{case_id}/review", response_model=SpecialPerformanceCaseResponse)
async def review_case(
    case_id: str,
    request: ReviewSpecialPerformanceCaseRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> SpecialPerformanceCaseResponse:
    case = await review_special_case(
        session, case_id=case_id, user=user, request=request
    )
    return await _case_response(session, case)


@router.post("/{case_id}/process-plugin", response_model=SpecialPerformanceCaseResponse)
async def process_case_plugin(
    case_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> SpecialPerformanceCaseResponse:
    case = await process_approved_special_case(
        session, case_id=case_id, user=user
    )
    return await _case_response(session, case)


@router.patch("/{case_id}/deadline", response_model=SpecialPerformanceCaseResponse)
async def update_case_deadline(
    case_id: str,
    request: AdjustSpecialPerformanceDeadlineRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> SpecialPerformanceCaseResponse:
    case = await adjust_special_case_deadline(
        session,
        case_id=case_id,
        user=user,
        review_due_at=request.review_due_at,
        reason=request.reason,
    )
    return await _case_response(session, case)
