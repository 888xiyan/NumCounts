"""Explicit, cycle-safe record links and dependency input resolution."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.functions import FunctionExecutionError
from app.models.calculation import CalculationRecord
from app.models.link import RecordLink, RecordLinkType
from app.schemas.links import CreateRecordLinkRequest


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class LinkResolution:
    waiting: bool
    input_data: dict[str, Any]
    snapshots: list[dict[str, Any]]


async def get_record_link(session: AsyncSession, *, link_id: str) -> RecordLink:
    link = await session.get(RecordLink, link_id)
    if link is None:
        raise APIError(
            status_code=404,
            code="RECORD_LINK_NOT_FOUND",
            message="record link was not found",
        )
    return link


async def list_record_links(
    session: AsyncSession, *, record_id: str | None = None
) -> list[RecordLink]:
    statement = select(RecordLink)
    if record_id is not None:
        statement = statement.where(RecordLink.source_record_id == record_id)
    return list(
        (
            await session.scalars(
                statement.order_by(RecordLink.created_at, RecordLink.id)
            )
        ).all()
    )


async def _record_exists(session: AsyncSession, record_id: str) -> CalculationRecord:
    record = await session.get(CalculationRecord, record_id)
    if record is None:
        raise APIError(
            status_code=404,
            code="CALCULATION_RECORD_NOT_FOUND",
            message="calculation record was not found",
        )
    return record


async def _would_create_cycle(
    session: AsyncSession, *, source_record_id: str, target_record_id: str
) -> bool:
    """Edges point from a dependent source to the target it consumes."""
    edges = list(
        (
            await session.execute(
                select(RecordLink.source_record_id, RecordLink.target_record_id)
            )
        ).all()
    )
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
    graph.setdefault(source_record_id, set()).add(target_record_id)

    stack = [target_record_id]
    visited: set[str] = set()
    while stack:
        current = stack.pop()
        if current == source_record_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        stack.extend(graph.get(current, set()) - visited)
    return False


async def create_record_link(
    session: AsyncSession, *, request: CreateRecordLinkRequest
) -> RecordLink:
    if request.source_record_id == request.target_record_id:
        raise APIError(
            status_code=422,
            code="RECORD_LINK_SELF_REFERENCE",
            message="a record cannot link to itself",
        )
    source = await _record_exists(session, request.source_record_id)
    await _record_exists(session, request.target_record_id)
    if source.status == "running":
        raise APIError(
            status_code=409,
            code="CALCULATION_ALREADY_RUNNING",
            message="links cannot change while a source record is running",
        )
    if await _would_create_cycle(
        session,
        source_record_id=request.source_record_id,
        target_record_id=request.target_record_id,
    ):
        raise APIError(
            status_code=409,
            code="RECORD_LINK_CYCLE",
            message="record link would create a dependency cycle",
        )
    link = RecordLink(
        source_record_id=request.source_record_id,
        target_record_id=request.target_record_id,
        link_type=RecordLinkType(request.link_type),
        input_key=request.input_key,
        target_path=request.target_path,
        created_at=_now(),
    )
    session.add(link)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise APIError(
            status_code=409,
            code="RECORD_LINK_INPUT_EXISTS",
            message="source record already has a link for this input key",
        ) from error
    await session.refresh(link)
    return link


async def delete_record_link(session: AsyncSession, *, link_id: str) -> RecordLink:
    link = await get_record_link(session, link_id=link_id)
    source = await _record_exists(session, link.source_record_id)
    if source.status == "running":
        raise APIError(
            status_code=409,
            code="CALCULATION_ALREADY_RUNNING",
            message="links cannot change while a source record is running",
        )
    await session.delete(link)
    await session.commit()
    return link


def _read_path(record: CalculationRecord, path: str) -> Any:
    root_name, *segments = path.split(".")
    value: Any = record.input_data if root_name == "input" else record.output_data
    for segment in segments:
        if not isinstance(value, dict) or segment not in value:
            raise FunctionExecutionError(
                "RECORD_LINK_PATH_NOT_FOUND",
                "linked record does not contain the requested path",
                {"record_id": record.id, "target_path": path},
            )
        value = value[segment]
    if value is None:
        raise FunctionExecutionError(
            "RECORD_LINK_PATH_NOT_FOUND",
            "linked record does not contain a usable value",
            {"record_id": record.id, "target_path": path},
        )
    return deepcopy(value)


async def resolve_linked_input(
    session: AsyncSession, *, record: CalculationRecord
) -> LinkResolution:
    links = await list_record_links(session, record_id=record.id)
    if not links:
        return LinkResolution(False, deepcopy(record.input_data), [])
    resolved_input = deepcopy(record.input_data)
    snapshots: list[dict[str, Any]] = []
    for link in links:
        target = await _record_exists(session, link.target_record_id)
        if link.link_type == RecordLinkType.EXECUTION:
            if target.status in {"pending", "waiting", "running", "stale"}:
                return LinkResolution(True, resolved_input, snapshots)
            if target.status != "success":
                raise FunctionExecutionError(
                    "RECORD_LINK_DEPENDENCY_FAILED",
                    "execution dependency did not complete successfully",
                    {
                        "link_id": link.id,
                        "target_record_id": target.id,
                        "target_status": target.status,
                    },
                )
        value = _read_path(target, link.target_path)
        resolved_input[link.input_key] = value
        snapshots.append(
            {
                "link_id": link.id,
                "link_type": link.link_type,
                "target_record_id": target.id,
                "target_version": target.lock_version,
                "target_path": link.target_path,
                "input_key": link.input_key,
                "value": value,
            }
        )
    return LinkResolution(False, resolved_input, snapshots)


async def invalidate_downstream_records(
    session: AsyncSession, *, target_record_id: str
) -> list[str]:
    """Mark all transitive dependents stale while retaining old output for review."""
    stale_ids: list[str] = []
    pending = [target_record_id]
    visited: set[str] = set()
    now = _now()
    while pending:
        target_id = pending.pop()
        if target_id in visited:
            continue
        visited.add(target_id)
        source_ids = list(
            (
                await session.scalars(
                    select(RecordLink.source_record_id).where(
                        RecordLink.target_record_id == target_id
                    )
                )
            ).all()
        )
        for source_id in source_ids:
            source = await session.get(CalculationRecord, source_id)
            if source is None or source.status == "running":
                continue
            if source.status not in {"pending", "waiting", "stale"}:
                source.status = "stale"
                source.error_code = "DEPENDENCY_CHANGED"
                source.error_message = (
                    "a linked record changed and this result is stale"
                )
                source.error_details = {"target_record_id": target_id}
                source.lock_version += 1
                source.updated_at = now
                stale_ids.append(source.id)
            pending.append(source_id)
    return stale_ids
