import asyncio
import hashlib
from datetime import UTC, datetime

import pytest

from app.core.config import ExternalExecutorSettings
from app.functions import FunctionExecutionError
from app.functions import snapshot as snapshot_service
from app.models.calculation import CalculationAttempt, CalculationRecord
from app.services import calculation_service
from app.services.link_service import LinkResolution


def test_registered_snapshot_contains_actual_source_and_is_verifiable() -> None:
    snapshot = snapshot_service.build_function_body_snapshot(
        {"kind": "registered", "name": "teaching_performance", "version": "1.0.0"}
    )

    assert snapshot["kind"] == "registered_python"
    assert "def _teaching_performance" in snapshot["body"]["source"]
    assert "class _TeachingInput" in snapshot["input_contract"]["model_source"]
    assert snapshot_service.verify_function_body_snapshot(snapshot) is True


def test_function_snapshot_digest_detects_tampering() -> None:
    snapshot = snapshot_service.build_function_body_snapshot(
        {"kind": "registered", "name": "course_bonus", "version": "1.0.0"}
    )
    snapshot["body"]["source"] = "def changed(): pass"

    assert snapshot_service.verify_function_body_snapshot(snapshot) is False
    assert snapshot_service.verify_function_body_snapshot(None) is None


def test_external_function_requires_deployment_source_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "def calculate_paper_performance(input_data):\n    return {'amount': 1}\n"
    executor = ExternalExecutorSettings(
        executor_id="research-policy-runner",
        base_url="https://executor.example.edu",
        function_artifacts=[
            {
                "name": "calculate_paper_performance",
                "version": "2.1.0",
                "source": source,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "dependencies": {"policy-runtime": "2.1.0"},
            }
        ],
    )
    monkeypatch.setattr(snapshot_service, "get_executor", lambda _: executor)

    snapshot = snapshot_service.build_function_body_snapshot(
        {
            "kind": "external",
            "executor_id": "research-policy-runner",
            "name": "calculate_paper_performance",
            "version": "2.1.0",
        }
    )

    assert snapshot["kind"] == "external_source_bundle"
    assert snapshot["body"]["source"] == source
    assert snapshot_service.verify_function_body_snapshot(snapshot) is True


def test_external_function_without_source_artifact_is_not_formally_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = ExternalExecutorSettings(
        executor_id="research-policy-runner", base_url="https://executor.example.edu"
    )
    monkeypatch.setattr(snapshot_service, "get_executor", lambda _: executor)

    with pytest.raises(FunctionExecutionError) as error:
        snapshot_service.build_function_body_snapshot(
            {
                "kind": "external",
                "executor_id": "research-policy-runner",
                "name": "calculate_paper_performance",
                "version": "2.1.0",
            }
        )

    assert error.value.code == "FUNCTION_SNAPSHOT_UNAVAILABLE"


def test_execution_attempt_persists_function_and_context_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    record = CalculationRecord(
        id="record-1",
        table_name="teaching_results",
        period_id="2026-spring",
        input_data={"hours": 36, "rate": 80, "quality_factor": 1.1},
        function_spec={
            "kind": "registered",
            "name": "teaching_performance",
            "version": "1.0.0",
        },
        requested_by_user_id="user-1",
        workflow_run_id="workflow-run-1",
        status="pending",
        attempt_count=0,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )

    class Result:
        def scalar_one_or_none(self) -> CalculationRecord:
            return record

    class Session:
        def __init__(self) -> None:
            self.added: list[CalculationAttempt] = []

        async def execute(self, _: object) -> Result:
            return Result()

        def add(self, item: CalculationAttempt) -> None:
            self.added.append(item)

        async def commit(self) -> None:
            return None

        async def refresh(self, _: CalculationRecord) -> None:
            return None

    async def resolve(_: object, *, record: CalculationRecord) -> LinkResolution:
        return LinkResolution(False, record.input_data, [])

    monkeypatch.setattr(calculation_service, "resolve_linked_input", resolve)
    session = Session()
    _, execution_id, execution_input = asyncio.run(
        calculation_service._start_execution(session, record_id=record.id)
    )

    assert execution_id is not None
    assert execution_input == record.input_data
    attempt = session.added[0]
    assert snapshot_service.verify_function_body_snapshot(
        attempt.function_body_snapshot
    ) is True
    assert attempt.execution_context_snapshot == {
        "schema_version": "numcounts.execution-context.v1",
        "record_id": "record-1",
        "table_name": "teaching_results",
        "period_id": "2026-spring",
        "requested_by_user_id": "user-1",
        "workflow_run_id": "workflow-run-1",
        "plugin": None,
    }
