from datetime import UTC, date, datetime

import pytest

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
    AchievementSource,
    AchievementStatus,
    AchievementType,
)
from app.models.user import User, UserRole


def _user(*, user_id: str, role: UserRole) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        username=f"{role.lower()}-{user_id}",
        password_hash="not-used-by-domain-tests",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_manual_declaration_binds_teacher_to_submitter() -> None:
    teacher = _user(user_id="teacher-1", role=UserRole.USER)
    record = create_manual_record(
        user=teacher,
        department_id="computer-science",
        achievement_type=AchievementType.SOCIAL_SERVICE,
        level="school",
        occurred_at=date(2026, 10, 16),
        payload={"hours": 8},
    )

    assert record.teacher_id == teacher.id
    assert record.submitted_by_user_id == teacher.id
    assert record.source == AchievementSource.MANUAL_DECLARATION
    assert record.status == AchievementStatus.PENDING_REVIEW
    assert not is_calculation_eligible(record)


def test_source_import_creates_pending_record_and_requires_admin_actor() -> None:
    draft = AchievementDraft(
        teacher_id="teacher-1",
        teacher_name="张老师",
        department_id="computer-science",
        achievement_type=AchievementType.TEACHING_WORKLOAD,
        level="undergraduate",
        occurred_at=date(2026, 9, 1),
        source_record_id="course-1001",
        payload={"hours": 36},
    )
    record = create_imported_record(
        source=AchievementSource.ACADEMIC_AFFAIRS, draft=draft
    )

    assert record.status == AchievementStatus.PENDING_REVIEW
    assert record.source_record_id == "course-1001"
    ensure_importer(_user(user_id="admin-1", role=UserRole.ADMIN))
    with pytest.raises(AchievementBusinessError) as denied:
        ensure_importer(_user(user_id="teacher-1", role=UserRole.USER))
    assert denied.value.code == "ACHIEVEMENT_IMPORT_FORBIDDEN"


def test_admin_review_is_the_only_path_to_calculation_eligibility() -> None:
    submitter = _user(user_id="teacher-1", role=UserRole.USER)
    reviewer = _user(user_id="admin-1", role=UserRole.ADMIN)
    record = create_manual_record(
        user=submitter,
        department_id="computer-science",
        achievement_type=AchievementType.RESEARCH_PAPER,
        level="A",
        occurred_at=date(2026, 10, 16),
        payload={"title": "Example paper"},
    )

    with pytest.raises(AchievementBusinessError) as denied:
        review_record(
            record=record,
            reviewer=submitter,
            decision="approve",
            comment=None,
        )
    assert denied.value.code == "ACHIEVEMENT_REVIEW_FORBIDDEN"
    assert record.status == AchievementStatus.PENDING_REVIEW

    review_record(
        record=record,
        reviewer=reviewer,
        decision="approve",
        comment="材料核验通过",
    )
    assert record.status == AchievementStatus.APPROVED
    assert record.reviewed_by_user_id == reviewer.id
    assert is_calculation_eligible(record)

    with pytest.raises(AchievementBusinessError) as repeated:
        review_record(
            record=record,
            reviewer=reviewer,
            decision="reject",
            comment="cannot replace conclusion",
        )
    assert repeated.value.code == "ACHIEVEMENT_ALREADY_REVIEWED"
