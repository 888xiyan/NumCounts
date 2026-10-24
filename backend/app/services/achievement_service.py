from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.domain.achievements import (
    AchievementBusinessError,
    AchievementDraft,
    create_imported_record,
    create_manual_record,
    ensure_importer,
    is_calculation_eligible,
    review_record,
)
from app.models.achievement import (
    AchievementRecord,
    AchievementSource,
    AchievementStatus,
    AchievementType,
)
from app.models.user import User, UserRole
from app.schemas.achievements import (
    ImportedAchievement,
    ManualDeclarationRequest,
    ReviewAchievementRequest,
)


def _as_api_error(error: AchievementBusinessError) -> APIError:
    status_code = 403 if error.code.endswith("FORBIDDEN") else 409
    if error.code == "USER_UNAVAILABLE":
        status_code = 401
    return APIError(
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )


def can_access_achievement(user: User, record: AchievementRecord) -> bool:
    return user.role == UserRole.ADMIN or (
        record.submitted_by_user_id == user.id
        or (user.teacher_id is not None and record.teacher_id == user.teacher_id)
    )


async def create_manual_declaration(
    session: AsyncSession, *, user: User, request: ManualDeclarationRequest
) -> AchievementRecord:
    try:
        record = create_manual_record(
            user=user,
            department_id=request.department_id,
            achievement_type=request.achievement_type,
            level=request.level,
            occurred_at=request.occurred_at,
            payload=request.payload,
        )
    except AchievementBusinessError as error:
        raise _as_api_error(error) from error
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def import_achievements(
    session: AsyncSession,
    *,
    importer: User,
    source: AchievementSource,
    records: list[ImportedAchievement],
) -> list[AchievementRecord]:
    try:
        ensure_importer(importer)
    except AchievementBusinessError as error:
        raise _as_api_error(error) from error
    source_ids = [record.source_record_id for record in records]
    if len(source_ids) != len(set(source_ids)):
        raise APIError(
            status_code=409,
            code="DUPLICATE_SOURCE_RECORD",
            message="source_record_id must be unique within an import request",
        )

    existing = await session.scalars(
        select(AchievementRecord.source_record_id).where(
            AchievementRecord.source == source,
            AchievementRecord.source_record_id.in_(source_ids),
        )
    )
    duplicate_ids = sorted(value for value in existing if value is not None)
    if duplicate_ids:
        raise APIError(
            status_code=409,
            code="DUPLICATE_SOURCE_RECORD",
            message="one or more source records have already been imported",
            details={"source_record_ids": duplicate_ids},
        )

    try:
        imported = [
            create_imported_record(
                source=source,
                draft=AchievementDraft(
                    teacher_id=item.teacher_id,
                    teacher_name=item.teacher_name,
                    department_id=item.department_id,
                    achievement_type=item.achievement_type,
                    level=item.level,
                    occurred_at=item.occurred_at,
                    source_record_id=item.source_record_id,
                    payload=item.payload,
                ),
            )
            for item in records
        ]
    except AchievementBusinessError as error:
        raise _as_api_error(error) from error
    session.add_all(imported)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise APIError(
            status_code=409,
            code="DUPLICATE_SOURCE_RECORD",
            message="one or more source records have already been imported",
        ) from error
    for record in imported:
        await session.refresh(record)
    return imported


async def get_achievement(
    session: AsyncSession, *, record_id: str, user: User
) -> AchievementRecord:
    record = await session.get(AchievementRecord, record_id)
    if record is None:
        raise APIError(
            status_code=404,
            code="ACHIEVEMENT_NOT_FOUND",
            message="achievement record was not found",
        )
    if not can_access_achievement(user, record):
        raise APIError(
            status_code=403,
            code="ACHIEVEMENT_ACCESS_DENIED",
            message="you cannot access this achievement record",
        )
    return record


async def list_achievements(
    session: AsyncSession,
    *,
    user: User,
    status: AchievementStatus | None = None,
    achievement_type: AchievementType | None = None,
    department_id: str | None = None,
    teacher_id: str | None = None,
    limit: int = 100,
    approved_only: bool = False,
) -> list[AchievementRecord]:
    statement = select(AchievementRecord)
    if approved_only:
        statement = statement.where(
            AchievementRecord.status == AchievementStatus.APPROVED
        )
    elif status is not None:
        statement = statement.where(AchievementRecord.status == status)
    if achievement_type is not None:
        statement = statement.where(
            AchievementRecord.achievement_type == achievement_type
        )
    if department_id is not None:
        statement = statement.where(AchievementRecord.department_id == department_id)
    if teacher_id is not None:
        statement = statement.where(AchievementRecord.teacher_id == teacher_id)
    if user.role != UserRole.ADMIN:
        ownership_filters = [AchievementRecord.submitted_by_user_id == user.id]
        if user.teacher_id is not None:
            ownership_filters.append(AchievementRecord.teacher_id == user.teacher_id)
        statement = statement.where(
            or_(*ownership_filters)
        )
    statement = statement.order_by(
        AchievementRecord.occurred_at, AchievementRecord.id
    ).limit(limit)
    return list((await session.scalars(statement)).all())


async def list_approved_for_calculation(
    session: AsyncSession,
    *,
    department_id: str | None = None,
    teacher_id: str | None = None,
    teacher_ids: list[str] | None = None,
    achievement_type: AchievementType | None = None,
    occurred_from: date | None = None,
    occurred_to: date | None = None,
    limit: int = 100,
) -> list[AchievementRecord]:
    """Internal input boundary for the future calculation-batch service.

    It intentionally receives no HTTP user object: access control belongs to its
    caller, while this function guarantees that non-approved records never cross
    from the data domain into the calculation domain.
    """
    statement = select(AchievementRecord).where(
        AchievementRecord.status == AchievementStatus.APPROVED
    )
    if department_id is not None:
        statement = statement.where(AchievementRecord.department_id == department_id)
    if teacher_id is not None:
        statement = statement.where(AchievementRecord.teacher_id == teacher_id)
    if teacher_ids is not None:
        statement = statement.where(AchievementRecord.teacher_id.in_(teacher_ids))
    if achievement_type is not None:
        statement = statement.where(
            AchievementRecord.achievement_type == achievement_type
        )
    if occurred_from is not None:
        statement = statement.where(AchievementRecord.occurred_at >= occurred_from)
    if occurred_to is not None:
        statement = statement.where(AchievementRecord.occurred_at <= occurred_to)
    statement = statement.order_by(
        AchievementRecord.occurred_at, AchievementRecord.id
    ).limit(limit)
    records = list((await session.scalars(statement)).all())
    return [record for record in records if is_calculation_eligible(record)]


async def review_achievement(
    session: AsyncSession,
    *,
    record_id: str,
    reviewer: User,
    request: ReviewAchievementRequest,
) -> AchievementRecord:
    result = await session.execute(
        select(AchievementRecord)
        .where(AchievementRecord.id == record_id)
        .with_for_update()
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise APIError(
            status_code=404,
            code="ACHIEVEMENT_NOT_FOUND",
            message="achievement record was not found",
        )
    try:
        review_record(
            record=record,
            reviewer=reviewer,
            decision=request.decision,
            comment=request.comment,
        )
    except AchievementBusinessError as error:
        raise _as_api_error(error) from error
    await session.commit()
    await session.refresh(record)
    return record
