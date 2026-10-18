from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


def _now() -> datetime:
    return datetime.now(UTC)


async def write_audit_event(
    session: AsyncSession,
    *,
    actor_user_id: str | None,
    event_type: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        created_at=_now(),
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


async def list_audit_events(
    session: AsyncSession, *, resource_id: str | None, limit: int
) -> list[AuditEvent]:
    statement = select(AuditEvent)
    if resource_id is not None:
        statement = statement.where(AuditEvent.resource_id == resource_id)
    return list(
        (
            await session.scalars(
                statement.order_by(AuditEvent.created_at.desc()).limit(limit)
            )
        ).all()
    )
