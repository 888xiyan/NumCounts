import csv
from datetime import UTC, date, datetime
from io import StringIO

import pytest
from pydantic import ValidationError

from app.core.errors import APIError
from app.models.achievement import (
    AchievementRecord,
    AchievementSource,
    AchievementStatus,
    AchievementType,
)
from app.models.formal_calculation import (
    FormalCalculationResult,
    FormalCalculationResultSource,
    FormalCalculationResultStatus,
)
from app.schemas.formal_calculations import (
    AchievementInputMapping,
    CreateFormalCalculationBatchRequest,
)
from app.services.formal_calculation_service import (
    _group_by_teacher,
    build_achievement_context,
    render_formal_result_csv,
)


def _achievement(
    record_id: str,
    *,
    teacher_id: str = "teacher-1",
    department_id: str = "computer-science",
    achievement_type: AchievementType = AchievementType.TEACHING_WORKLOAD,
    level: str = "standard",
    payload: dict = {"hours": 12},
) -> AchievementRecord:
    now = datetime.now(UTC)
    return AchievementRecord(
        id=record_id,
        teacher_id=teacher_id,
        teacher_name="教师一",
        department_id=department_id,
        achievement_type=achievement_type,
        level=level,
        occurred_at=date(2026, 3, 1),
        source=AchievementSource.ACADEMIC_AFFAIRS,
        source_record_id=record_id,
        payload=payload,
        status=AchievementStatus.APPROVED,
        created_at=now,
        updated_at=now,
    )


def test_batch_request_rejects_invalid_period_and_duplicate_mapping_keys() -> None:
    with pytest.raises(ValidationError, match="occurred_from"):
        CreateFormalCalculationBatchRequest.model_validate(
            {
                "period_id": "2026-spring",
                "occurred_from": "2026-06-01",
                "occurred_to": "2026-03-01",
                "workflow_id": "11111111-1111-1111-1111-111111111111",
                "result_node_key": "total",
                "input_mappings": [{"context_key": "hours", "aggregation": "count"}],
            }
        )

    with pytest.raises(ValidationError, match="repeat context_key"):
        CreateFormalCalculationBatchRequest.model_validate(
            {
                "period_id": "2026-spring",
                "occurred_from": "2026-03-01",
                "occurred_to": "2026-06-01",
                "workflow_id": "11111111-1111-1111-1111-111111111111",
                "result_node_key": "total",
                "input_mappings": [
                    {"context_key": "hours", "aggregation": "count"},
                    {"context_key": "hours", "aggregation": "count"},
                ],
            }
        )


def test_achievement_context_uses_only_declared_fixed_aggregations() -> None:
    records = [
        _achievement("achievement-1", payload={"hours": 12}),
        _achievement("achievement-2", payload={"hours": 18}),
        _achievement(
            "achievement-3",
            achievement_type=AchievementType.RESEARCH_PAPER,
            payload={"hours": 99},
        ),
    ]
    mappings = [
        AchievementInputMapping(
            context_key="approved_hours",
            aggregation="sum",
            achievement_type=AchievementType.TEACHING_WORKLOAD,
            payload_key="hours",
        ),
        AchievementInputMapping(
            context_key="paper_count",
            aggregation="count",
            achievement_type=AchievementType.RESEARCH_PAPER,
        ),
    ]

    assert build_achievement_context(records, mappings) == {
        "approved_hours": 30.0,
        "paper_count": 1,
    }


def test_achievement_context_rejects_non_numeric_sum_values() -> None:
    mappings = [
        AchievementInputMapping(
            context_key="approved_hours",
            aggregation="sum",
            payload_key="hours",
        )
    ]

    with pytest.raises(APIError) as error:
        build_achievement_context([_achievement("achievement-1", payload={})], mappings)

    assert error.value.detail["code"] == "ACHIEVEMENT_MAPPING_VALUE_INVALID"


def test_requested_teacher_without_approved_source_is_rejected() -> None:
    with pytest.raises(APIError) as error:
        _group_by_teacher(
            [_achievement("achievement-1")], requested_teacher_ids=["teacher-2"]
        )

    assert error.value.detail["code"] == "NO_APPROVED_ACHIEVEMENTS"


def test_formal_result_export_contains_only_saved_source_snapshot_fields() -> None:
    now = datetime.now(UTC)
    result = FormalCalculationResult(
        id="result-1",
        batch_id="batch-1",
        teacher_id="teacher-1",
        teacher_name="教师一",
        department_id="computer-science",
        period_id="2026-spring",
        result_version=2,
        status=FormalCalculationResultStatus.SUCCESS,
        total_amount=2400.0,
        result_data={"total": {"amount": 2400.0}},
        created_at=now,
        finished_at=now,
    )
    source = FormalCalculationResultSource(
        id="source-1",
        result_id=result.id,
        achievement_id="achievement-1",
        achievement_snapshot={
            "achievement_type": "teaching_workload",
            "level": "standard",
            "occurred_at": "2026-03-01",
            "source": "academic_affairs",
            "source_record_id": "workload-1",
            "payload": {"hours": 30},
        },
        created_at=now,
    )

    rows = list(
        csv.DictReader(
            StringIO(render_formal_result_csv([result], {result.id: [source]}))
        )
    )

    assert rows == [
        {
            "batch_id": "batch-1",
            "period_id": "2026-spring",
            "teacher_id": "teacher-1",
            "teacher_name": "教师一",
            "department_id": "computer-science",
            "result_version": "2",
            "total_amount": "2400.0",
            "workflow_run_id": "",
            "achievement_id": "achievement-1",
            "achievement_type": "teaching_workload",
            "achievement_level": "standard",
            "achievement_occurred_at": "2026-03-01",
            "achievement_source": "academic_affairs",
            "achievement_source_record_id": "workload-1",
        }
    ]
