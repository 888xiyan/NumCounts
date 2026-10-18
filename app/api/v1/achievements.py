from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_session
from app.models.achievement import AchievementSource, AchievementStatus, AchievementType
from app.models.user import User, UserRole
from app.schemas.achievements import (
    AchievementListResponse,
    AchievementResponse,
    ImportAchievementsRequest,
    ImportAchievementsResponse,
    ManualDeclarationRequest,
    ReviewAchievementRequest,
)
from app.services.achievement_service import (
    create_manual_declaration,
    get_achievement,
    import_achievements,
    list_achievements,
    review_achievement,
)

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.post(
    "/declarations",
    response_model=AchievementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_declaration(
    request: ManualDeclarationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AchievementResponse:
    return await create_manual_declaration(session, user=user, request=request)


@router.post(
    "/import",
    response_model=ImportAchievementsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_records(
    request: ImportAchievementsRequest,
    session: AsyncSession = Depends(get_session),
    importer: User = Depends(require_role(UserRole.ADMIN)),
) -> ImportAchievementsResponse:
    records = await import_achievements(
        session,
        importer=importer,
        source=AchievementSource(request.source),
        records=request.records,
    )
    return ImportAchievementsResponse(imported=len(records), records=records)


@router.get("/eligible", response_model=AchievementListResponse)
async def list_eligible_records(
    achievement_type: AchievementType | None = None,
    department_id: str | None = Query(default=None, max_length=64),
    teacher_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AchievementListResponse:
    records = await list_achievements(
        session,
        user=user,
        achievement_type=achievement_type,
        department_id=department_id,
        teacher_id=teacher_id,
        limit=limit,
        approved_only=True,
    )
    return AchievementListResponse(data=records)


@router.get("", response_model=AchievementListResponse)
async def list_records(
    status_filter: AchievementStatus | None = Query(default=None, alias="status"),
    achievement_type: AchievementType | None = None,
    department_id: str | None = Query(default=None, max_length=64),
    teacher_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AchievementListResponse:
    records = await list_achievements(
        session,
        user=user,
        status=status_filter,
        achievement_type=achievement_type,
        department_id=department_id,
        teacher_id=teacher_id,
        limit=limit,
    )
    return AchievementListResponse(data=records)


@router.get("/{record_id}", response_model=AchievementResponse)
async def get_record(
    record_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AchievementResponse:
    return await get_achievement(session, record_id=record_id, user=user)


@router.post("/{record_id}/review", response_model=AchievementResponse)
async def review_record(
    record_id: str,
    request: ReviewAchievementRequest,
    session: AsyncSession = Depends(get_session),
    reviewer: User = Depends(require_role(UserRole.ADMIN)),
) -> AchievementResponse:
    return await review_achievement(
        session, record_id=record_id, reviewer=reviewer, request=request
    )
