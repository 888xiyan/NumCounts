from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.audit import AuditEvent
from app.models.user import User, UserRole
from app.schemas.audit import AuditEventListResponse, AuditEventResponse
from app.services.audit_service import list_audit_events

router = APIRouter(prefix="/audit-events", tags=["audit-events"])


def _response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        actor_user_id=event.actor_user_id,
        event_type=event.event_type,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        details=event.details,
        created_at=event.created_at,
    )


@router.get("", response_model=AuditEventListResponse)
async def list_events(
    resource_id: str | None = Query(default=None, min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> AuditEventListResponse:
    events = await list_audit_events(
        session, resource_id=resource_id, limit=limit
    )
    return AuditEventListResponse(data=[_response(event) for event in events])
