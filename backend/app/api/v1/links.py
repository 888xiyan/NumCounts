from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.link import RecordLink
from app.models.user import User, UserRole
from app.schemas.links import (
    CreateRecordLinkRequest,
    RecordLinkListResponse,
    RecordLinkResponse,
)
from app.services.audit_service import write_audit_event
from app.services.link_service import (
    create_record_link,
    delete_record_link,
    list_record_links,
)

router = APIRouter(prefix="/record-links", tags=["record-links"])


def _response(link: RecordLink) -> RecordLinkResponse:
    return RecordLinkResponse(
        id=link.id,
        source_record_id=link.source_record_id,
        target_record_id=link.target_record_id,
        link_type=link.link_type,
        input_key=link.input_key,
        target_path=link.target_path,
        created_at=link.created_at,
    )


@router.post("", response_model=RecordLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_link(
    request: CreateRecordLinkRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> RecordLinkResponse:
    link = await create_record_link(session, request=request)
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="record_link.created",
        resource_type="record_link",
        resource_id=link.id,
        details={
            "source_record_id": link.source_record_id,
            "target_record_id": link.target_record_id,
            "link_type": link.link_type,
        },
    )
    return _response(link)


@router.get("", response_model=RecordLinkListResponse)
async def list_links(
    source_record_id: str | None = Query(default=None, min_length=36, max_length=36),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RecordLinkListResponse:
    links = await list_record_links(session, record_id=source_record_id)
    return RecordLinkListResponse(data=[_response(link) for link in links])


@router.delete("/{link_id}", response_model=RecordLinkResponse)
async def remove_link(
    link_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> RecordLinkResponse:
    link = await delete_record_link(session, link_id=link_id)
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="record_link.deleted",
        resource_type="record_link",
        resource_id=link.id,
        details={
            "source_record_id": link.source_record_id,
            "target_record_id": link.target_record_id,
        },
    )
    return _response(link)
