"""Pure policy for the achievement-data MVP.

The policy deliberately has no FastAPI or database dependency.  HTTP routes,
scheduled imports, and future workflows all call the same application service
and therefore share the same review boundary.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.models.achievement import (
    AchievementRecord,
    AchievementSource,
    AchievementStatus,
    AchievementType,
)
from app.models.user import User, UserRole


class AchievementBusinessError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class AchievementDraft:
    teacher_id: str
    teacher_name: str
    department_id: str
    achievement_type: AchievementType
    level: str
    occurred_at: Any
    payload: dict[str, Any]
    source_record_id: str | None = None


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_active_user(user: User) -> None:
    if not user.is_active:
        raise AchievementBusinessError(
            "USER_UNAVAILABLE", "user is unavailable for achievement operations"
        )


def ensure_importer(user: User) -> None:
    ensure_active_user(user)
    if user.role != UserRole.ADMIN:
        raise AchievementBusinessError(
            "ACHIEVEMENT_IMPORT_FORBIDDEN",
            "only an administrator can import source achievements",
        )


def ensure_reviewer(user: User) -> None:
    """The MVP assigns the reviewer responsibility to ADMIN."""
    ensure_active_user(user)
    if user.role != UserRole.ADMIN:
        raise AchievementBusinessError(
            "ACHIEVEMENT_REVIEW_FORBIDDEN",
            "only an administrator can review an achievement",
        )


def create_manual_record(
    *, user: User, department_id: str, achievement_type: AchievementType,
    level: str, occurred_at: Any, payload: dict[str, Any], now: datetime | None = None
) -> AchievementRecord:
    ensure_active_user(user)
    if user.teacher_id is None:
        raise AchievementBusinessError(
            "TEACHER_PROFILE_NOT_LINKED",
            "member account is not linked to a teacher profile",
        )
    timestamp = now or now_utc()
    return AchievementRecord(
        teacher_id=user.teacher_id,
        teacher_name=user.username,
        department_id=department_id,
        achievement_type=achievement_type,
        level=level,
        occurred_at=occurred_at,
        source=AchievementSource.MANUAL_DECLARATION,
        payload=payload,
        status=AchievementStatus.PENDING_REVIEW,
        submitted_by_user_id=user.id,
        created_at=timestamp,
        updated_at=timestamp,
    )


def create_imported_record(
    *, source: AchievementSource, draft: AchievementDraft,
    now: datetime | None = None
) -> AchievementRecord:
    if source not in {
        AchievementSource.ACADEMIC_AFFAIRS,
        AchievementSource.RESEARCH_SYSTEM,
    }:
        raise AchievementBusinessError(
            "INVALID_ACHIEVEMENT_SOURCE",
            "only academic affairs and research system sources can be imported",
        )
    if not draft.source_record_id:
        raise AchievementBusinessError(
            "MISSING_SOURCE_RECORD_ID",
            "imported achievements require a source record id",
        )
    timestamp = now or now_utc()
    return AchievementRecord(
        teacher_id=draft.teacher_id,
        teacher_name=draft.teacher_name,
        department_id=draft.department_id,
        achievement_type=draft.achievement_type,
        level=draft.level,
        occurred_at=draft.occurred_at,
        source=source,
        source_record_id=draft.source_record_id,
        payload=draft.payload,
        status=AchievementStatus.PENDING_REVIEW,
        created_at=timestamp,
        updated_at=timestamp,
    )


def review_record(
    *, record: AchievementRecord, reviewer: User,
    decision: Literal["approve", "reject"], comment: str | None,
    now: datetime | None = None
) -> AchievementRecord:
    ensure_reviewer(reviewer)
    if record.status != AchievementStatus.PENDING_REVIEW:
        raise AchievementBusinessError(
            "ACHIEVEMENT_ALREADY_REVIEWED",
            "only pending achievement records can be reviewed",
            {"status": record.status},
        )
    timestamp = now or now_utc()
    record.status = (
        AchievementStatus.APPROVED
        if decision == "approve"
        else AchievementStatus.REJECTED
    )
    record.reviewed_by_user_id = reviewer.id
    record.reviewed_at = timestamp
    record.review_comment = comment
    record.updated_at = timestamp
    return record


def is_calculation_eligible(record: AchievementRecord) -> bool:
    """Only an approved source record may be transformed into calculation input."""
    return record.status == AchievementStatus.APPROVED
