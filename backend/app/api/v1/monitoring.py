from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.calculation import CalculationAttempt, CalculationRecord
from app.models.link import RecordLink
from app.models.user import User, UserRole
from app.schemas.monitoring import RecoveryResponse, RuntimeSummaryResponse
from app.services.audit_service import write_audit_event
from app.services.calculation_service import recover_interrupted_records

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/summary", response_model=RuntimeSummaryResponse)
async def runtime_summary(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RuntimeSummaryResponse:
    status_rows = list(
        (
            await session.execute(
                select(CalculationRecord.status, func.count()).group_by(
                    CalculationRecord.status
                )
            )
        ).all()
    )
    oldest_pending_at = await session.scalar(
        select(func.min(CalculationRecord.created_at)).where(
            CalculationRecord.status.in_(("pending", "waiting"))
        )
    )
    oldest_running_at = await session.scalar(
        select(func.min(CalculationRecord.updated_at)).where(
            CalculationRecord.status == "running"
        )
    )
    records_by_status = {name: count for name, count in status_rows}
    return RuntimeSummaryResponse(
        records_by_status=records_by_status,
        total_record_count=sum(records_by_status.values()),
        failed_record_count=records_by_status.get("failed", 0),
        oldest_pending_at=oldest_pending_at,
        oldest_running_at=oldest_running_at,
        record_link_count=(
            await session.scalar(select(func.count()).select_from(RecordLink)) or 0
        ),
        running_attempt_count=await session.scalar(
            select(func.count())
            .select_from(CalculationAttempt)
            .where(CalculationAttempt.status == "running")
        )
        or 0,
    )


@router.post("/recover-interrupted", response_model=RecoveryResponse)
async def recover_interrupted(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> RecoveryResponse:
    records = await recover_interrupted_records(session)
    for record in records:
        await write_audit_event(
            session,
            actor_user_id=user.id,
            event_type="calculation.recovered",
            resource_type="calculation_record",
            resource_id=record.id,
            details={"error_code": record.error_code},
        )
    return RecoveryResponse(
        recovered=len(records),
        records=[{"id": record.id, "status": record.status} for record in records],
    )
