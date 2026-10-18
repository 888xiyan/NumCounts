import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.calculation import CalculationRecord
from app.models.link import RecordLink, RecordLinkType
from app.schemas.links import CreateRecordLinkRequest
from app.services import link_service


def _record(
    record_id: str, *, status: str, output: dict | None = None
) -> CalculationRecord:
    now = datetime.now(UTC)
    return CalculationRecord(
        id=record_id,
        table_name="performance_results",
        input_data={"base": 10},
        function_spec={
            "kind": "registered",
            "name": "teaching_performance",
            "version": "1.0.0",
        },
        output_data=output,
        status=status,
        attempt_count=0,
        lock_version=2,
        created_at=now,
        updated_at=now,
    )


def _link(*, link_type: RecordLinkType = RecordLinkType.EXECUTION) -> RecordLink:
    return RecordLink(
        id="link-1",
        source_record_id="source-1",
        target_record_id="target-1",
        link_type=link_type,
        input_key="linked_amount",
        target_path="output.amount",
        created_at=datetime.now(UTC),
    )


def test_record_link_contract_rejects_uncontrolled_paths() -> None:
    with pytest.raises(ValidationError):
        CreateRecordLinkRequest.model_validate(
            {
                "source_record_id": "1" * 36,
                "target_record_id": "2" * 36,
                "link_type": "data",
                "input_key": "amount",
                "target_path": "__class__.__dict__",
            }
        )


def test_execution_link_resolves_success_output_into_attempt_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _record("source-1", status="pending")
    target = _record("target-1", status="success", output={"amount": 3168})

    async def links(*args: object, **kwargs: object) -> list[RecordLink]:
        return [_link()]

    async def record_exists(*args: object) -> CalculationRecord:
        return source if args[-1] == "source-1" else target

    monkeypatch.setattr(link_service, "list_record_links", links)
    monkeypatch.setattr(link_service, "_record_exists", record_exists)

    resolution = asyncio.run(link_service.resolve_linked_input(object(), record=source))

    assert resolution.waiting is False
    assert resolution.input_data == {"base": 10, "linked_amount": 3168}
    assert resolution.snapshots[0]["target_version"] == 2


def test_execution_link_waits_for_pending_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _record("source-1", status="pending")
    target = _record("target-1", status="pending")

    async def links(*args: object, **kwargs: object) -> list[RecordLink]:
        return [_link()]

    async def record_exists(*args: object) -> CalculationRecord:
        return source if args[-1] == "source-1" else target

    monkeypatch.setattr(link_service, "list_record_links", links)
    monkeypatch.setattr(link_service, "_record_exists", record_exists)

    resolution = asyncio.run(link_service.resolve_linked_input(object(), record=source))

    assert resolution.waiting is True
