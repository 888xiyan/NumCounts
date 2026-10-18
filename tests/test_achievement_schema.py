from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models.achievement import (
    AchievementRecord,
    AchievementSource,
    AchievementStatus,
    AchievementType,
)
from app.schemas.achievements import (
    AchievementResponse,
    ImportAchievementsRequest,
    ManualDeclarationRequest,
)


def test_manual_declaration_does_not_accept_a_teacher_override() -> None:
    with pytest.raises(ValidationError):
        ManualDeclarationRequest.model_validate(
            {
                "teacher_id": "another-teacher",
                "department_id": "computer-science",
                "achievement_type": "social_service",
                "level": "school",
                "occurred_at": "2026-10-16",
            }
        )


def test_imported_record_uses_pending_review_status() -> None:
    request = ImportAchievementsRequest.model_validate(
        {
            "source": "academic_affairs",
            "records": [
                {
                    "source_record_id": "course-1001",
                    "teacher_id": "teacher-1",
                    "teacher_name": "张老师",
                    "department_id": "computer-science",
                    "achievement_type": "teaching_workload",
                    "level": "undergraduate",
                    "occurred_at": "2026-09-01",
                    "payload": {"hours": 36},
                }
            ],
        }
    )

    record = request.records[0]
    assert record.achievement_type == AchievementType.TEACHING_WORKLOAD
    assert record.occurred_at == date(2026, 9, 1)
    assert AchievementStatus.PENDING_REVIEW.value == "pending_review"


def test_manual_declaration_requires_a_department() -> None:
    with pytest.raises(ValidationError):
        ManualDeclarationRequest.model_validate(
            {
                "achievement_type": "research_paper",
                "level": "A",
                "occurred_at": "2026-10-16",
            }
        )


def test_achievement_response_supports_orm_records() -> None:
    now = datetime.now(UTC)
    record = AchievementRecord(
        id="achievement-1",
        teacher_id="teacher-1",
        teacher_name="张老师",
        department_id="computer-science",
        achievement_type=AchievementType.RESEARCH_PAPER,
        level="A",
        occurred_at=date(2026, 10, 16),
        source=AchievementSource.MANUAL_DECLARATION,
        payload={"title": "A paper"},
        status=AchievementStatus.PENDING_REVIEW,
        created_at=now,
        updated_at=now,
    )

    response = AchievementResponse.model_validate(record)

    assert response.id == "achievement-1"
    assert response.status == AchievementStatus.PENDING_REVIEW
