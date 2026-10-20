"""Workflow and persistence rules for material-backed special cases."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import APIError
from app.models.achievement import (
    AchievementRecord,
    AchievementSource,
    AchievementStatus,
)
from app.models.calculation import CalculationRecord
from app.models.formal_calculation import (
    FormalCalculationBatch,
    FormalCalculationBatchStatus,
    FormalCalculationResult,
    FormalCalculationResultStatus,
)
from app.models.plugin import RulePluginPurpose, RulePluginStatus
from app.models.special_performance import (
    SpecialPerformanceCase,
    SpecialPerformanceCaseEvent,
    SpecialPerformanceCaseMaterial,
    SpecialPerformanceCaseStatus,
    SpecialPerformanceCaseType,
)
from app.models.user import User, UserRole
from app.schemas.special_performance import (
    CreateSpecialPerformanceCaseRequest,
    HandleSpecialPerformanceCaseRequest,
    ReviewSpecialPerformanceCaseRequest,
    SpecialPerformancePluginOutput,
    UpdateSpecialPerformanceCaseRequest,
)
from app.services.audit_service import write_audit_event
from app.services.calculation_service import (
    create_record_from_plugin_snapshot,
    execute_record,
)
from app.services.member_service import require_teacher_id
from app.services.plugin_service import (
    get_rule_plugin,
    plugin_snapshot,
)

MATERIAL_MAX_BYTES = 10 * 1024 * 1024
MATERIAL_MAX_COUNT = 20
CASE_FORM_MAX_BYTES = 64 * 1024
DEFAULT_REVIEW_DAYS = 3
MATERIAL_KEY_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
MEDIA_TYPE_PATTERN = re.compile(r"^[\w.+-]+/[\w.+-]+$")


def _now() -> datetime:
    return datetime.now(UTC)


def _processing_lease_is_active(case: SpecialPerformanceCase) -> bool:
    updated_at = case.updated_at
    updated_at_utc = (
        updated_at.replace(tzinfo=UTC)
        if updated_at.tzinfo is None
        else updated_at.astimezone(UTC)
    )
    return updated_at_utc > _now() - timedelta(minutes=15)


def _ensure_json_object(value: dict[str, Any], *, field: str) -> None:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise APIError(
            status_code=422,
            code="INVALID_CASE_DATA",
            message=f"{field} must contain only JSON values",
        ) from error
    if len(encoded.encode()) > CASE_FORM_MAX_BYTES:
        raise APIError(
            status_code=422,
            code="CASE_DATA_TOO_LARGE",
            message=f"{field} cannot exceed 64 KiB",
        )


def _error_detail(error: APIError) -> dict[str, Any]:
    detail = error.detail if isinstance(error.detail, dict) else {}
    return {
        "code": str(detail.get("code", "SPECIAL_PLUGIN_FAILED")),
        "message": str(detail.get("message", "special case plugin failed")),
        "details": detail.get("details"),
    }


def _event(
    session: AsyncSession,
    *,
    case: SpecialPerformanceCase,
    event_type: str,
    actor: User | None,
    from_status: SpecialPerformanceCaseStatus | None = None,
    to_status: SpecialPerformanceCaseStatus | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        SpecialPerformanceCaseEvent(
            case_id=case.id,
            event_type=event_type,
            from_status=str(from_status) if from_status else None,
            to_status=str(to_status) if to_status else None,
            actor_user_id=actor.id if actor else None,
            details=details or {},
            created_at=_now(),
        )
    )


async def _audit(
    session: AsyncSession,
    *,
    case: SpecialPerformanceCase,
    actor: User | None,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    await write_audit_event(
        session,
        actor_user_id=actor.id if actor else None,
        event_type=event_type,
        resource_type="special_performance_case",
        resource_id=case.id,
        details=details or {},
    )


async def _case_for_update(
    session: AsyncSession, *, case_id: str
) -> SpecialPerformanceCase:
    result = await session.execute(
        select(SpecialPerformanceCase)
        .where(SpecialPerformanceCase.id == case_id)
        .with_for_update()
    )
    case = result.scalar_one_or_none()
    if case is None:
        raise APIError(
            status_code=404,
            code="SPECIAL_CASE_NOT_FOUND",
            message="special-performance case was not found",
        )
    return case


def _ensure_member_owner(case: SpecialPerformanceCase, user: User) -> None:
    if user.role != UserRole.ADMIN and case.submitted_by_user_id != user.id:
        raise APIError(
            status_code=404,
            code="SPECIAL_CASE_NOT_FOUND",
            message="special-performance case was not found",
        )


def _ensure_draft(case: SpecialPerformanceCase) -> None:
    if case.status != SpecialPerformanceCaseStatus.DRAFT:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_IMMUTABLE_AFTER_SUBMISSION",
            message="only draft cases and their materials can be changed",
            details={"status": str(case.status)},
        )


async def create_special_case(
    session: AsyncSession,
    *,
    user: User,
    request: CreateSpecialPerformanceCaseRequest,
) -> SpecialPerformanceCase:
    teacher_id = require_teacher_id(user)
    _ensure_json_object(request.form_data, field="form_data")
    original_result: FormalCalculationResult | None = None
    if request.case_type == SpecialPerformanceCaseType.APPEAL:
        original_result = await session.get(
            FormalCalculationResult, request.original_result_id
        )
        if (
            original_result is None
            or original_result.teacher_id != teacher_id
            or original_result.status != FormalCalculationResultStatus.SUCCESS
        ):
            raise APIError(
                status_code=404,
                code="FORMAL_RESULT_NOT_FOUND",
                message="appeal target result was not found",
            )
        batch = await session.get(FormalCalculationBatch, original_result.batch_id)
        if batch is None or batch.status != FormalCalculationBatchStatus.REVIEWED:
            raise APIError(
                status_code=409,
                code="FORMAL_RESULT_NOT_APPEALABLE",
                message="only reviewed formal results can be appealed",
            )
        teacher_name = original_result.teacher_name
        department_id = original_result.department_id
        period_id = original_result.period_id
    else:
        teacher_name = request.teacher_name
        department_id = request.department_id
        period_id = request.period_id

    now = _now()
    case = SpecialPerformanceCase(
        case_type=SpecialPerformanceCaseType(request.case_type),
        status=SpecialPerformanceCaseStatus.DRAFT,
        submitted_by_user_id=user.id,
        teacher_id=teacher_id,
        teacher_name=teacher_name,
        department_id=department_id,
        period_id=period_id,
        original_result_id=original_result.id if original_result else None,
        title=request.title,
        form_data=request.form_data,
        submission_version=0,
        created_at=now,
        updated_at=now,
    )
    session.add(case)
    await session.flush()
    _event(
        session,
        case=case,
        event_type="case_created",
        actor=user,
        to_status=SpecialPerformanceCaseStatus.DRAFT,
        details={"case_type": str(case.case_type)},
    )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_CREATED",
        details={"case_type": str(case.case_type)},
    )
    return case


async def update_special_case(
    session: AsyncSession,
    *,
    case_id: str,
    user: User,
    request: UpdateSpecialPerformanceCaseRequest,
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    _ensure_member_owner(case, user)
    _ensure_draft(case)
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise APIError(
            status_code=422,
            code="EMPTY_CASE_UPDATE",
            message="at least one case field must be provided",
        )
    if "form_data" in updates and updates["form_data"] is not None:
        _ensure_json_object(updates["form_data"], field="form_data")
    for field, value in updates.items():
        if value is not None:
            setattr(case, field, value)
    case.updated_at = _now()
    _event(
        session,
        case=case,
        event_type="draft_updated",
        actor=user,
        from_status=case.status,
        to_status=case.status,
        details={"fields": sorted(updates)},
    )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_DRAFT_UPDATED",
        details={"fields": sorted(updates)},
    )
    return case


async def add_case_material(
    session: AsyncSession,
    *,
    case_id: str,
    material_key: str,
    filename: str,
    media_type: str,
    content: bytes,
    user: User,
) -> SpecialPerformanceCaseMaterial:
    if not MATERIAL_KEY_PATTERN.fullmatch(material_key):
        raise APIError(
            status_code=422,
            code="INVALID_MATERIAL_KEY",
            message="material_key must be a simple stable identifier",
        )
    safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not safe_filename
        or len(safe_filename) > 255
        or any(ord(char) < 32 for char in safe_filename)
    ):
        raise APIError(
            status_code=422,
            code="INVALID_MATERIAL_FILENAME",
            message="filename is invalid",
        )
    if not MEDIA_TYPE_PATTERN.fullmatch(media_type):
        media_type = "application/octet-stream"
    if not content or len(content) > MATERIAL_MAX_BYTES:
        raise APIError(
            status_code=413 if len(content) > MATERIAL_MAX_BYTES else 422,
            code="MATERIAL_SIZE_INVALID",
            message="material content must be between 1 byte and 10 MiB",
        )
    case = await _case_for_update(session, case_id=case_id)
    _ensure_member_owner(case, user)
    _ensure_draft(case)
    existing = await session.scalars(
        select(SpecialPerformanceCaseMaterial)
        .where(
            SpecialPerformanceCaseMaterial.case_id == case.id,
            SpecialPerformanceCaseMaterial.material_key == material_key,
        )
        .with_for_update()
    )
    prior_versions = list(existing.all())
    if not any(item.is_current for item in prior_versions):
        current_ids = await session.scalars(
            select(SpecialPerformanceCaseMaterial.id).where(
                SpecialPerformanceCaseMaterial.case_id == case.id,
                SpecialPerformanceCaseMaterial.is_current.is_(True),
            )
        )
        if len(list(current_ids)) >= MATERIAL_MAX_COUNT:
            raise APIError(
                status_code=409,
                code="CASE_MATERIAL_LIMIT_REACHED",
                message="a case can have at most 20 current materials",
            )
    version = max((item.version for item in prior_versions), default=0) + 1
    for item in prior_versions:
        item.is_current = False
    now = _now()
    material = SpecialPerformanceCaseMaterial(
        case_id=case.id,
        material_key=material_key,
        version=version,
        filename=safe_filename,
        media_type=media_type,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        content=content,
        is_current=True,
        uploaded_by_user_id=user.id,
        created_at=now,
    )
    session.add(material)
    case.updated_at = now
    await session.flush()
    _event(
        session,
        case=case,
        event_type="material_added_or_replaced",
        actor=user,
        from_status=case.status,
        to_status=case.status,
        details={
            "material_id": material.id,
            "material_key": material_key,
            "version": version,
            "sha256": material.sha256,
        },
    )
    await session.commit()
    await session.refresh(material)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_MATERIAL_SAVED",
        details={"material_id": material.id, "version": version},
    )
    return material


async def remove_case_material(
    session: AsyncSession,
    *,
    case_id: str,
    material_id: str,
    user: User,
) -> SpecialPerformanceCaseMaterial:
    case = await _case_for_update(session, case_id=case_id)
    _ensure_member_owner(case, user)
    _ensure_draft(case)
    material = await session.get(SpecialPerformanceCaseMaterial, material_id)
    if material is None or material.case_id != case.id or not material.is_current:
        raise APIError(
            status_code=404,
            code="CASE_MATERIAL_NOT_FOUND",
            message="current case material was not found",
        )
    material.is_current = False
    case.updated_at = _now()
    _event(
        session,
        case=case,
        event_type="material_removed_from_draft",
        actor=user,
        from_status=case.status,
        to_status=case.status,
        details={"material_id": material.id, "sha256": material.sha256},
    )
    await session.commit()
    await session.refresh(material)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_MATERIAL_REMOVED",
        details={"material_id": material.id},
    )
    return material


async def current_case_materials(
    session: AsyncSession, *, case_id: str, only_current: bool = False
) -> list[SpecialPerformanceCaseMaterial]:
    statement = select(SpecialPerformanceCaseMaterial).where(
        SpecialPerformanceCaseMaterial.case_id == case_id
    ).options(
        load_only(
            SpecialPerformanceCaseMaterial.id,
            SpecialPerformanceCaseMaterial.case_id,
            SpecialPerformanceCaseMaterial.material_key,
            SpecialPerformanceCaseMaterial.version,
            SpecialPerformanceCaseMaterial.filename,
            SpecialPerformanceCaseMaterial.media_type,
            SpecialPerformanceCaseMaterial.sha256,
            SpecialPerformanceCaseMaterial.size_bytes,
            SpecialPerformanceCaseMaterial.is_current,
            SpecialPerformanceCaseMaterial.uploaded_by_user_id,
            SpecialPerformanceCaseMaterial.created_at,
        )
    )
    if only_current:
        statement = statement.where(SpecialPerformanceCaseMaterial.is_current.is_(True))
    statement = statement.order_by(
        SpecialPerformanceCaseMaterial.material_key,
        SpecialPerformanceCaseMaterial.version,
    )
    return list((await session.scalars(statement)).all())


async def case_events(
    session: AsyncSession, *, case_id: str
) -> list[SpecialPerformanceCaseEvent]:
    statement = (
        select(SpecialPerformanceCaseEvent)
        .where(SpecialPerformanceCaseEvent.case_id == case_id)
        .order_by(
            SpecialPerformanceCaseEvent.created_at, SpecialPerformanceCaseEvent.id
        )
    )
    return list((await session.scalars(statement)).all())


async def get_special_case(
    session: AsyncSession, *, case_id: str, user: User
) -> SpecialPerformanceCase:
    case = await session.get(SpecialPerformanceCase, case_id)
    if case is None:
        raise APIError(
            status_code=404,
            code="SPECIAL_CASE_NOT_FOUND",
            message="special-performance case was not found",
        )
    _ensure_member_owner(case, user)
    return case


async def list_special_cases(
    session: AsyncSession,
    *,
    user: User,
    status: SpecialPerformanceCaseStatus | None = None,
    overdue_only: bool = False,
    limit: int = 100,
) -> list[SpecialPerformanceCase]:
    statement = select(SpecialPerformanceCase)
    if user.role != UserRole.ADMIN:
        statement = statement.where(
            SpecialPerformanceCase.submitted_by_user_id == user.id
        )
    if status is not None:
        statement = statement.where(SpecialPerformanceCase.status == status)
    if overdue_only:
        statement = statement.where(
            SpecialPerformanceCase.status.in_(
                (
                    SpecialPerformanceCaseStatus.SUBMITTED,
                    SpecialPerformanceCaseStatus.REVIEWING,
                )
            ),
            SpecialPerformanceCase.review_due_at < _now(),
        )
    statement = statement.order_by(
        SpecialPerformanceCase.created_at.desc(), SpecialPerformanceCase.id
    ).limit(limit)
    return list((await session.scalars(statement)).all())


async def submit_special_case(
    session: AsyncSession, *, case_id: str, user: User
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    _ensure_member_owner(case, user)
    _ensure_draft(case)
    materials = await current_case_materials(
        session, case_id=case.id, only_current=True
    )
    if not materials:
        raise APIError(
            status_code=409,
            code="CASE_MATERIAL_REQUIRED",
            message="at least one current material is required before submission",
        )
    now = _now()
    case.submission_version += 1
    case.submitted_at = now
    case.review_due_at = now + timedelta(days=DEFAULT_REVIEW_DAYS)
    case.status = SpecialPerformanceCaseStatus.SUBMITTED
    case.processed_by_user_id = None
    case.reviewed_by_user_id = None
    case.processing_comment = None
    case.review_comment = None
    case.plugin_id = None
    case.plugin_snapshot = None
    case.plugin_execution_status = None
    case.calculation_record_id = None
    case.achievement_id = None
    case.processing_error = None
    case.updated_at = now
    original_snapshot: dict[str, Any] | None = None
    if case.original_result_id is not None:
        original = await session.get(FormalCalculationResult, case.original_result_id)
        if original is None:
            raise APIError(
                status_code=409,
                code="APPEAL_TARGET_RESULT_UNAVAILABLE",
                message="appeal target formal result is no longer available",
            )
        original_snapshot = {
            "id": original.id,
            "period_id": original.period_id,
            "result_version": original.result_version,
            "total_amount": original.total_amount,
            "result": original.result_data,
        }
    case.submitted_snapshot = {
        "schema_version": "numcounts.special-case-submission.v1",
        "case_id": case.id,
        "case_type": str(case.case_type),
        "submission_version": case.submission_version,
        "teacher_id": case.teacher_id,
        "teacher_name": case.teacher_name,
        "department_id": case.department_id,
        "period_id": case.period_id,
        "title": case.title,
        "form_data": case.form_data,
        "original_result": original_snapshot,
        "materials": [
            {
                "id": material.id,
                "material_key": material.material_key,
                "version": material.version,
                "filename": material.filename,
                "media_type": material.media_type,
                "sha256": material.sha256,
                "size_bytes": material.size_bytes,
            }
            for material in materials
        ],
        "submitted_at": now.isoformat(),
    }
    _ensure_json_object(case.submitted_snapshot, field="submitted snapshot")
    _event(
        session,
        case=case,
        event_type="case_submitted",
        actor=user,
        from_status=SpecialPerformanceCaseStatus.DRAFT,
        to_status=case.status,
        details={
            "submission_version": case.submission_version,
            "review_due_at": case.review_due_at.isoformat(),
            "material_count": len(materials),
            "submitted_snapshot": case.submitted_snapshot,
        },
    )
    _event(
        session,
        case=case,
        event_type="notification_requested",
        actor=None,
        from_status=case.status,
        to_status=case.status,
        details={"reason": "case_submitted", "delivery": "not_implemented"},
    )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_SUBMITTED",
        details={
            "submission_version": case.submission_version,
            "review_due_at": case.review_due_at.isoformat(),
        },
    )
    return case


async def handle_special_case(
    session: AsyncSession,
    *,
    case_id: str,
    user: User,
    request: HandleSpecialPerformanceCaseRequest,
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    if request.action == "start_review":
        if case.status != SpecialPerformanceCaseStatus.SUBMITTED:
            raise APIError(
                status_code=409,
                code="SPECIAL_CASE_NOT_SUBMITTED",
                message="only submitted cases can enter review",
                details={"status": str(case.status)},
            )
        previous_status = case.status
        case.status = SpecialPerformanceCaseStatus.REVIEWING
        case.processed_by_user_id = user.id
        case.processing_comment = request.comment
        event_type = "case_review_started"
    else:
        if case.status not in {
            SpecialPerformanceCaseStatus.SUBMITTED,
            SpecialPerformanceCaseStatus.REVIEWING,
        }:
            raise APIError(
                status_code=409,
                code="SPECIAL_CASE_NOT_RETURNABLE",
                message="only submitted or reviewing cases can be returned to draft",
                details={"status": str(case.status)},
            )
        previous_status = case.status
        case.status = SpecialPerformanceCaseStatus.DRAFT
        case.processing_comment = request.comment
        event_type = "case_returned_to_draft"
    case.updated_at = _now()
    _event(
        session,
        case=case,
        event_type=event_type,
        actor=user,
        from_status=previous_status,
        to_status=case.status,
        details={"comment": request.comment},
    )
    if case.status == SpecialPerformanceCaseStatus.DRAFT:
        _event(
            session,
            case=case,
            event_type="notification_requested",
            actor=None,
            from_status=case.status,
            to_status=case.status,
            details={"reason": "case_returned_to_draft", "delivery": "not_implemented"},
        )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type=(
            "SPECIAL_CASE_REVIEW_STARTED"
            if case.status == SpecialPerformanceCaseStatus.REVIEWING
            else "SPECIAL_CASE_RETURNED_TO_DRAFT"
        ),
        details={"comment": request.comment},
    )
    return case


async def adjust_special_case_deadline(
    session: AsyncSession,
    *,
    case_id: str,
    user: User,
    review_due_at: datetime,
    reason: str,
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    if case.status not in {
        SpecialPerformanceCaseStatus.SUBMITTED,
        SpecialPerformanceCaseStatus.REVIEWING,
    }:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_DEADLINE_NOT_ADJUSTABLE",
            message="deadline can only be adjusted for submitted or reviewing cases",
            details={"status": str(case.status)},
        )
    new_due = (
        review_due_at.replace(tzinfo=UTC)
        if review_due_at.tzinfo is None
        else review_due_at.astimezone(UTC)
    )
    old_due = case.review_due_at
    case.review_due_at = new_due
    case.updated_at = _now()
    _event(
        session,
        case=case,
        event_type="review_deadline_adjusted",
        actor=user,
        from_status=case.status,
        to_status=case.status,
        details={
            "previous_due_at": old_due.isoformat() if old_due else None,
            "review_due_at": new_due.isoformat(),
            "reason": reason,
        },
    )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_DEADLINE_ADJUSTED",
        details={"review_due_at": new_due.isoformat(), "reason": reason},
    )
    return case


async def _execute_case_plugin(
    session: AsyncSession,
    *,
    case: SpecialPerformanceCase,
    actor: User,
) -> SpecialPerformanceCase:
    if case.status != SpecialPerformanceCaseStatus.APPROVED:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_PLUGIN_NOT_READY",
            message="only approved cases can be processed by the special plugin",
            details={"status": str(case.status)},
        )
    if case.plugin_snapshot is None or case.plugin_id is None:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_PLUGIN_MISSING",
            message="approved case has no frozen processing plugin",
        )
    if case.submitted_snapshot is None:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_SUBMISSION_SNAPSHOT_MISSING",
            message="approved case has no frozen submission snapshot",
        )

    existing_record: CalculationRecord | None = None
    if case.calculation_record_id is not None:
        existing_record = await session.get(
            CalculationRecord, case.calculation_record_id
        )
    if case.plugin_execution_status == "running":
        lease_is_active = _processing_lease_is_active(case)
        if lease_is_active or (
            existing_record is not None and existing_record.status == "running"
        ):
            raise APIError(
                status_code=409,
                code="SPECIAL_CASE_PLUGIN_RUNNING",
                message="special processing plugin is already running",
                retryable=True,
            )
    try:
        if case.plugin_execution_status == "running":
            _event(
                session,
                case=case,
                event_type="processing_plugin_resumed",
                actor=actor,
                from_status=case.status,
                to_status=case.status,
                details={
                    "calculation_record_id": case.calculation_record_id,
                    "submission_version": case.submission_version,
                },
            )
        else:
            _event(
                session,
                case=case,
                event_type="processing_plugin_started",
                actor=actor,
                from_status=case.status,
                to_status=case.status,
                details={
                    "plugin_id": case.plugin_id,
                    "submission_version": case.submission_version,
                },
            )
        case.plugin_execution_status = "running"
        case.updated_at = _now()
        await session.commit()

        if existing_record is None:
            key_source = f"{case.id}:{case.submission_version}:special-plugin"
            idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_URL, key_source))
            existing_record = await create_record_from_plugin_snapshot(
                session,
                table_name="special_performance_cases",
                period_id=case.period_id,
                input_data={
                    "case_snapshot": case.submitted_snapshot,
                    "materials": case.submitted_snapshot["materials"],
                },
                plugin_snapshot=case.plugin_snapshot,
                idempotency_key=idempotency_key,
                requested_by_user_id=actor.id,
            )
            case.calculation_record_id = existing_record.id
            await session.commit()

        if existing_record.status in {"pending", "waiting"}:
            existing_record = await execute_record(
                session, record_id=existing_record.id
            )
        if existing_record.status != "success":
            raise APIError(
                status_code=409,
                code=existing_record.error_code or "SPECIAL_CASE_PLUGIN_FAILED",
                message=existing_record.error_message
                or "special processing plugin failed",
                details=existing_record.error_details,
            )
        try:
            normalized = SpecialPerformancePluginOutput.model_validate(
                existing_record.output_data
            )
        except ValidationError as error:
            raise APIError(
                status_code=422,
                code="SPECIAL_CASE_PLUGIN_OUTPUT_INVALID",
                message="special processing plugin returned an invalid output",
                details={"errors": error.errors(include_input=False)},
            ) from error
        _ensure_json_object(normalized.payload, field="plugin payload")
        achievement = AchievementRecord(
            teacher_id=case.teacher_id,
            teacher_name=case.teacher_name,
            department_id=case.department_id,
            achievement_type=normalized.achievement_type,
            level=normalized.level,
            occurred_at=normalized.occurred_at,
            source=AchievementSource.SPECIAL_PERFORMANCE,
            source_record_id=f"{case.id}:{case.submission_version}",
            payload=normalized.payload,
            status=AchievementStatus.APPROVED,
            submitted_by_user_id=case.submitted_by_user_id,
            reviewed_by_user_id=case.reviewed_by_user_id,
            reviewed_at=case.updated_at,
            review_comment=case.review_comment,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(achievement)
        await session.flush()
        previous_status = case.status
        case.status = SpecialPerformanceCaseStatus.PROCESSED
        case.plugin_execution_status = "success"
        case.achievement_id = achievement.id
        case.processing_error = None
        case.updated_at = _now()
        _event(
            session,
            case=case,
            event_type="case_processed",
            actor=actor,
            from_status=previous_status,
            to_status=case.status,
            details={
                "achievement_id": achievement.id,
                "calculation_record_id": existing_record.id,
                "plugin_id": case.plugin_id,
            },
        )
        _event(
            session,
            case=case,
            event_type="notification_requested",
            actor=None,
            from_status=case.status,
            to_status=case.status,
            details={"reason": "case_processed", "delivery": "not_implemented"},
        )
        await session.commit()
        await session.refresh(case)
        await _audit(
            session,
            case=case,
            actor=actor,
            event_type="SPECIAL_CASE_PLUGIN_SUCCEEDED",
            details={
                "achievement_id": achievement.id,
                "calculation_record_id": existing_record.id,
                "plugin_id": case.plugin_id,
            },
        )
        return case
    except Exception as error:
        await session.rollback()
        refreshed_case = await session.get(
            SpecialPerformanceCase, case.id, populate_existing=True
        )
        if refreshed_case is None:
            raise
        case = refreshed_case
        if case.status == SpecialPerformanceCaseStatus.PROCESSED:
            return case
        detail = (
            _error_detail(error)
            if isinstance(error, APIError)
            else {
                "code": "SPECIAL_CASE_PLUGIN_UNEXPECTED_ERROR",
                "message": "special processing plugin failed unexpectedly",
                "details": None,
            }
        )
        previous_status = case.status
        case.status = SpecialPerformanceCaseStatus.DRAFT
        case.plugin_execution_status = "failed"
        case.processing_error = detail
        case.updated_at = _now()
        _event(
            session,
            case=case,
            event_type="processing_plugin_failed",
            actor=actor,
            from_status=previous_status,
            to_status=case.status,
            details={
                **detail,
                "calculation_record_id": case.calculation_record_id,
                "submission_version": case.submission_version,
            },
        )
        _event(
            session,
            case=case,
            event_type="notification_requested",
            actor=None,
            from_status=case.status,
            to_status=case.status,
            details={"reason": "plugin_failed", "delivery": "not_implemented"},
        )
        await session.commit()
        await session.refresh(case)
        await _audit(
            session,
            case=case,
            actor=actor,
            event_type="SPECIAL_CASE_PLUGIN_FAILED",
            details=detail,
        )
        return case


async def review_special_case(
    session: AsyncSession,
    *,
    case_id: str,
    user: User,
    request: ReviewSpecialPerformanceCaseRequest,
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    if case.status != SpecialPerformanceCaseStatus.REVIEWING:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_NOT_REVIEWING",
            message="only reviewing cases can be approved or returned",
            details={"status": str(case.status)},
        )
    previous_status = case.status
    case.reviewed_by_user_id = user.id
    case.review_comment = request.comment
    case.updated_at = _now()
    if request.action == "return_to_draft":
        case.status = SpecialPerformanceCaseStatus.DRAFT
        _event(
            session,
            case=case,
            event_type="case_returned_to_draft",
            actor=user,
            from_status=previous_status,
            to_status=case.status,
            details={"comment": request.comment, "stage": "review"},
        )
        _event(
            session,
            case=case,
            event_type="notification_requested",
            actor=None,
            from_status=case.status,
            to_status=case.status,
            details={"reason": "case_returned_to_draft", "delivery": "not_implemented"},
        )
        await session.commit()
        await session.refresh(case)
        await _audit(
            session,
            case=case,
            actor=user,
            event_type="SPECIAL_CASE_REVIEW_RETURNED",
            details={"comment": request.comment},
        )
        return case

    assert request.plugin_id is not None
    plugin = await get_rule_plugin(session, plugin_id=request.plugin_id)
    if plugin.status != RulePluginStatus.ENABLED:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_PLUGIN_DISABLED",
            message="the dedicated special-case plugin must be enabled",
        )
    if plugin.purpose != RulePluginPurpose.SPECIAL_CASE:
        raise APIError(
            status_code=409,
            code="SPECIAL_CASE_PLUGIN_PURPOSE_REQUIRED",
            message="approval requires a plugin dedicated to special cases",
        )
    case.status = SpecialPerformanceCaseStatus.APPROVED
    case.plugin_id = plugin.id
    case.plugin_snapshot = plugin_snapshot(plugin)
    case.plugin_execution_status = "pending"
    case.calculation_record_id = None
    case.achievement_id = None
    case.processing_error = None
    _event(
        session,
        case=case,
        event_type="case_approved",
        actor=user,
        from_status=previous_status,
        to_status=case.status,
        details={
            "plugin_id": plugin.id,
            "plugin_key": plugin.plugin_key,
            "plugin_version": plugin.version,
            "comment": request.comment,
        },
    )
    _event(
        session,
        case=case,
        event_type="notification_requested",
        actor=None,
        from_status=case.status,
        to_status=case.status,
        details={"reason": "case_approved", "delivery": "not_implemented"},
    )
    await session.commit()
    await session.refresh(case)
    await _audit(
        session,
        case=case,
        actor=user,
        event_type="SPECIAL_CASE_APPROVED",
        details={"plugin_id": plugin.id},
    )
    return await _execute_case_plugin(session, case=case, actor=user)


async def process_approved_special_case(
    session: AsyncSession, *, case_id: str, user: User
) -> SpecialPerformanceCase:
    case = await _case_for_update(session, case_id=case_id)
    return await _execute_case_plugin(session, case=case, actor=user)


async def adjust_deadline_for_admin(
    session: AsyncSession,
    *,
    case_id: str,
    user: User,
    review_due_at: datetime,
    reason: str,
) -> SpecialPerformanceCase:
    if user.role != UserRole.ADMIN:
        raise APIError(
            status_code=403,
            code="INSUFFICIENT_PERMISSIONS",
            message="insufficient permissions",
        )
    return await adjust_special_case_deadline(
        session,
        case_id=case_id,
        user=user,
        review_due_at=review_due_at,
        reason=reason,
    )


async def load_case_material(
    session: AsyncSession,
    *,
    case_id: str,
    material_id: str,
    user: User,
) -> tuple[SpecialPerformanceCase, SpecialPerformanceCaseMaterial]:
    case = await get_special_case(session, case_id=case_id, user=user)
    material = await session.get(SpecialPerformanceCaseMaterial, material_id)
    if material is None or material.case_id != case.id:
        raise APIError(
            status_code=404,
            code="CASE_MATERIAL_NOT_FOUND",
            message="case material was not found",
        )
    return case, material


async def list_case_materials(
    session: AsyncSession, *, case_id: str, user: User
) -> list[SpecialPerformanceCaseMaterial]:
    await get_special_case(session, case_id=case_id, user=user)
    return await current_case_materials(session, case_id=case_id)
