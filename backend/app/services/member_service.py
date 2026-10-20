"""Member self-service access boundaries for trials and formal results."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.formal_calculation import (
    FormalCalculationBatch,
    FormalCalculationBatchStatus,
    FormalCalculationResult,
    FormalCalculationResultStatus,
)
from app.models.user import User


def require_teacher_id(user: User) -> str:
    if user.teacher_id is None:
        raise APIError(
            status_code=409,
            code="TEACHER_PROFILE_NOT_LINKED",
            message="member account is not linked to a teacher profile",
        )
    return user.teacher_id


async def list_member_formal_results(
    session: AsyncSession,
    *,
    teacher_id: str,
    period_id: str | None,
    limit: int,
) -> list[FormalCalculationResult]:
    """Return only confirmed, successful formal results for one teacher."""
    statement = (
        select(FormalCalculationResult)
        .join(
            FormalCalculationBatch,
            FormalCalculationResult.batch_id == FormalCalculationBatch.id,
        )
        .where(
            FormalCalculationResult.teacher_id == teacher_id,
            FormalCalculationResult.status == FormalCalculationResultStatus.SUCCESS,
            FormalCalculationBatch.status == FormalCalculationBatchStatus.REVIEWED,
        )
    )
    if period_id is not None:
        statement = statement.where(FormalCalculationResult.period_id == period_id)
    statement = statement.order_by(
        FormalCalculationResult.created_at.desc(),
        FormalCalculationResult.result_version.desc(),
    ).limit(limit)
    return list((await session.scalars(statement)).all())
