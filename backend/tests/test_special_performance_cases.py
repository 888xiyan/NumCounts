import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.core.errors import APIError
from app.models.achievement import AchievementRecord
from app.models.calculation import CalculationRecord
from app.models.special_performance import (
    SpecialPerformanceCase,
    SpecialPerformanceCaseStatus,
    SpecialPerformanceCaseType,
)
from app.models.user import User, UserRole
from app.schemas.special_performance import (
    CreateSpecialPerformanceCaseRequest,
    HandleSpecialPerformanceCaseRequest,
    ReviewSpecialPerformanceCaseRequest,
    SpecialPerformancePluginOutput,
)
from app.services.special_performance_service import (
    _ensure_draft,
    _execute_case_plugin,
    handle_special_case,
    submit_special_case,
)


def _case(status: SpecialPerformanceCaseStatus) -> SpecialPerformanceCase:
    now = datetime.now(UTC)
    return SpecialPerformanceCase(
        id="case-0001",
        case_type=SpecialPerformanceCaseType.SPECIAL_PERFORMANCE,
        status=status,
        submitted_by_user_id="member-1",
        teacher_id="teacher-1",
        teacher_name="教师一",
        department_id="department-1",
        period_id="2026-spring",
        title="特殊成果申报",
        form_data={"description": "校级专项工作"},
        submission_version=0,
        created_at=now,
        updated_at=now,
    )


def _user(user_id: str, role: UserRole) -> User:
    now = datetime.now(UTC)
    return User(
        id=user_id,
        username=user_id,
        teacher_id="teacher-1" if role == UserRole.USER else None,
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


class FakeResult:
    def __init__(self, item: object) -> None:
        self.item = item

    def scalar_one_or_none(self) -> object:
        return self.item

    def all(self) -> list[object]:
        return self.item if isinstance(self.item, list) else []


class FakeSession:
    def __init__(
        self, case: SpecialPerformanceCase, materials: list[object] | None = None
    ):
        self.case = case
        self.materials = materials or []
        self.added: list[object] = []

    async def execute(self, statement: object) -> FakeResult:
        return FakeResult(self.case)

    async def scalars(self, statement: object) -> FakeResult:
        return FakeResult(self.materials)

    async def get(self, model: object, record_id: str) -> object | None:
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        return None

    async def refresh(self, item: object) -> None:
        return None


def test_case_schemas_require_appeal_target_and_special_case_identity() -> None:
    with pytest.raises(ValidationError, match="original formal result"):
        CreateSpecialPerformanceCaseRequest.model_validate(
            {
                "case_type": "appeal",
                "title": "申诉 2026 春季绩效",
                "form_data": {"reason": "遗漏成果"},
            }
        )

    with pytest.raises(ValidationError, match="teacher name"):
        CreateSpecialPerformanceCaseRequest.model_validate(
            {
                "case_type": "special_performance",
                "title": "特殊成果申报",
                "period_id": "2026-spring",
                "form_data": {"reason": "专项工作"},
            }
        )


def test_review_approval_requires_dedicated_plugin_and_return_comment() -> None:
    with pytest.raises(ValidationError, match="requires a dedicated rule plugin"):
        ReviewSpecialPerformanceCaseRequest.model_validate({"action": "approve"})
    with pytest.raises(ValidationError, match="comment is required"):
        ReviewSpecialPerformanceCaseRequest.model_validate(
            {"action": "return_to_draft"}
        )


def test_special_plugin_output_is_normalized_and_rejects_extra_fields() -> None:
    output = SpecialPerformancePluginOutput.model_validate(
        {
            "achievement_type": "social_service",
            "level": "school",
            "occurred_at": "2026-04-01",
            "payload": {"points": 10},
        }
    )
    assert output.payload == {"points": 10}
    with pytest.raises(ValidationError):
        SpecialPerformancePluginOutput.model_validate(
            {
                "achievement_type": "social_service",
                "level": "school",
                "occurred_at": "2026-04-01",
                "payload": {"points": 10},
                "teacher_id": "forged-teacher",
            }
        )


def test_submitted_case_cannot_be_edited() -> None:
    with pytest.raises(APIError) as error:
        _ensure_draft(_case(SpecialPerformanceCaseStatus.SUBMITTED))
    assert error.value.detail["code"] == "SPECIAL_CASE_IMMUTABLE_AFTER_SUBMISSION"


def test_admin_handling_moves_submitted_case_to_reviewing() -> None:
    case = _case(SpecialPerformanceCaseStatus.SUBMITTED)
    session = FakeSession(case)
    with patch(
        "app.services.special_performance_service._audit", new=AsyncMock()
    ):
        result = asyncio.run(
            handle_special_case(
                session,  # type: ignore[arg-type]
                case_id=case.id,
                user=_user("admin-1", UserRole.ADMIN),
                request=HandleSpecialPerformanceCaseRequest(action="start_review"),
            )
        )

    assert result.status == SpecialPerformanceCaseStatus.REVIEWING
    assert result.processed_by_user_id == "admin-1"
    assert any(
        getattr(event, "event_type", None) == "case_review_started"
        for event in session.added
    )


def test_member_submission_freezes_materials_and_sets_three_day_deadline() -> None:
    case = _case(SpecialPerformanceCaseStatus.DRAFT)
    now = datetime.now(UTC)

    class Material:
        id = "material-1"
        material_key = "proof"
        version = 2
        filename = "proof.pdf"
        media_type = "application/pdf"
        sha256 = "a" * 64
        size_bytes = 128

    session = FakeSession(case, materials=[Material()])
    with patch(
        "app.services.special_performance_service._audit", new=AsyncMock()
    ):
        result = asyncio.run(
            submit_special_case(
                session,  # type: ignore[arg-type]
                case_id=case.id,
                user=_user("member-1", UserRole.USER),
            )
        )

    assert result.status == SpecialPerformanceCaseStatus.SUBMITTED
    assert result.submission_version == 1
    assert result.review_due_at is not None
    assert timedelta(days=3) - timedelta(seconds=2) <= (
        result.review_due_at - result.submitted_at
    ) <= timedelta(days=3) + timedelta(seconds=2)
    assert result.submitted_snapshot is not None
    assert result.submitted_snapshot["materials"][0]["sha256"] == "a" * 64
    assert any(
        getattr(event, "event_type", None) == "case_submitted"
        for event in session.added
    )
    submission_event = next(
        event for event in session.added if event.event_type == "case_submitted"
    )
    assert submission_event.details["submitted_snapshot"]["submission_version"] == 1
    assert (
        submission_event.details["submitted_snapshot"]["materials"][0]["sha256"]
        == "a" * 64
    )
    assert any(
        getattr(event, "event_type", None) == "notification_requested"
        for event in session.added
    )
    assert result.submitted_at is not None and result.submitted_at >= now


def test_submission_requires_at_least_one_material() -> None:
    session = FakeSession(_case(SpecialPerformanceCaseStatus.DRAFT))
    with pytest.raises(APIError) as error:
        asyncio.run(
            submit_special_case(
                session,  # type: ignore[arg-type]
                case_id=session.case.id,
                user=_user("member-1", UserRole.USER),
            )
        )
    assert error.value.detail["code"] == "CASE_MATERIAL_REQUIRED"


def test_special_plugin_creation_failure_returns_case_to_draft() -> None:
    case = _case(SpecialPerformanceCaseStatus.APPROVED)
    case.submission_version = 1
    case.plugin_id = "plugin-special"
    case.plugin_snapshot = {"id": case.plugin_id, "function": {"kind": "registered"}}
    case.submitted_snapshot = {"materials": [{"id": "material-frozen"}]}

    class ExecutionSession(FakeSession):
        async def get(
            self, model: object, record_id: str, **kwargs: object
        ) -> object | None:
            if model is SpecialPerformanceCase:
                return self.case
            if model is CalculationRecord:
                return None
            return None

        async def rollback(self) -> None:
            return None

        async def flush(self) -> None:
            return None

    session = ExecutionSession(case)
    failure = APIError(
        status_code=422,
        code="FUNCTION_NOT_FOUND",
        message="plugin function is unavailable",
    )
    with (
        patch(
            "app.services.special_performance_service.create_record_from_plugin_snapshot",
            new=AsyncMock(side_effect=failure),
        ) as create_record,
        patch("app.services.special_performance_service._audit", new=AsyncMock()),
    ):
        result = asyncio.run(
            _execute_case_plugin(
                session,  # type: ignore[arg-type]
                case=case,
                actor=_user("admin-1", UserRole.ADMIN),
            )
        )

    assert result.status == SpecialPerformanceCaseStatus.DRAFT
    assert result.plugin_execution_status == "failed"
    assert result.processing_error["code"] == "FUNCTION_NOT_FOUND"
    assert create_record.await_args.kwargs["input_data"]["materials"] == [
        {"id": "material-frozen"}
    ]
    assert any(
        getattr(event, "event_type", None) == "processing_plugin_failed"
        for event in session.added
    )


def test_special_plugin_rejects_a_recent_concurrent_run() -> None:
    case = _case(SpecialPerformanceCaseStatus.APPROVED)
    case.plugin_id = "plugin-special"
    case.plugin_snapshot = {"id": case.plugin_id, "function": {"kind": "registered"}}
    case.submitted_snapshot = {"materials": []}
    case.plugin_execution_status = "running"

    with pytest.raises(APIError) as error:
        asyncio.run(
            _execute_case_plugin(
                FakeSession(case),  # type: ignore[arg-type]
                case=case,
                actor=_user("admin-1", UserRole.ADMIN),
            )
        )

    assert error.value.detail["code"] == "SPECIAL_CASE_PLUGIN_RUNNING"


def test_special_plugin_success_creates_approved_achievement_source() -> None:
    case = _case(SpecialPerformanceCaseStatus.APPROVED)
    case.submission_version = 2
    case.plugin_id = "plugin-special"
    case.plugin_snapshot = {"id": case.plugin_id, "function": {"kind": "registered"}}
    case.submitted_snapshot = {"materials": [{"id": "frozen-material"}]}
    case.reviewed_by_user_id = "admin-1"
    calculation_record = SimpleNamespace(
        id="calculation-1",
        status="success",
        output_data={
            "achievement_type": "social_service",
            "level": "school",
            "occurred_at": "2026-05-01",
            "payload": {"points": 7},
        },
    )
    class AchievementSession(FakeSession):
        async def flush(self) -> None:
            for item in self.added:
                if isinstance(item, AchievementRecord) and item.id is None:
                    item.id = "achievement-1"

    session = AchievementSession(case)
    with (
        patch(
            "app.services.special_performance_service.create_record_from_plugin_snapshot",
            new=AsyncMock(return_value=calculation_record),
        ) as create_record,
        patch("app.services.special_performance_service._audit", new=AsyncMock()),
    ):
        result = asyncio.run(
            _execute_case_plugin(
                session,  # type: ignore[arg-type]
                case=case,
                actor=_user("admin-1", UserRole.ADMIN),
            )
        )

    achievements = [item for item in session.added if hasattr(item, "achievement_type")]
    assert result.status == SpecialPerformanceCaseStatus.PROCESSED
    assert result.calculation_record_id == "calculation-1"
    assert result.achievement_id is not None
    assert len(achievements) == 1
    assert achievements[0].source == "special_performance"
    assert achievements[0].source_record_id == f"{case.id}:2"
    assert achievements[0].reviewed_by_user_id == "admin-1"
    assert create_record.await_args.kwargs["input_data"]["materials"] == [
        {"id": "frozen-material"}
    ]
