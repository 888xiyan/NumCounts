"""Administrator-only, versioned formal performance calculation batches."""

import csv
from collections import defaultdict
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.achievement import AchievementRecord
from app.models.formal_calculation import (
    FormalCalculationBatch,
    FormalCalculationBatchStatus,
    FormalCalculationResult,
    FormalCalculationResultSource,
    FormalCalculationResultStatus,
)
from app.models.user import User
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunMode,
    WorkflowStatus,
)
from app.schemas.formal_calculations import (
    AchievementInputMapping,
    CreateFormalCalculationBatchRequest,
)
from app.schemas.workflows import StartWorkflowRunRequest
from app.services.achievement_service import list_approved_for_calculation
from app.services.audit_service import write_audit_event
from app.services.workflow_service import (
    get_workflow_definition,
    list_workflow_nodes,
    start_workflow_run,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _error_snapshot(error: APIError) -> tuple[str, str, dict[str, Any] | None]:
    detail = error.detail
    if not isinstance(detail, dict):
        return "FORMAL_CALCULATION_FAILED", str(detail), None
    return (
        str(detail.get("code", "FORMAL_CALCULATION_FAILED")),
        str(detail.get("message", "formal calculation failed")),
        detail.get("details") if isinstance(detail.get("details"), dict) else None,
    )


def _workflow_snapshot(
    workflow: WorkflowDefinition, *, nodes: list[Any]
) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "workflow_key": workflow.workflow_key,
        "version": workflow.version,
        "name": workflow.name,
        "nodes": [
            {
                "node_key": node.node_key,
                "node_type": node.node_type,
                "position": node.position,
                "config": node.config,
                "plugin": node.plugin_snapshot,
            }
            for node in nodes
        ],
    }


def _achievement_snapshot(record: AchievementRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "teacher_id": record.teacher_id,
        "teacher_name": record.teacher_name,
        "department_id": record.department_id,
        "achievement_type": str(record.achievement_type),
        "level": record.level,
        "occurred_at": record.occurred_at.isoformat(),
        "source": str(record.source),
        "source_record_id": record.source_record_id,
        "payload": record.payload,
        "status": str(record.status),
        "reviewed_by_user_id": record.reviewed_by_user_id,
        "reviewed_at": record.reviewed_at.isoformat()
        if record.reviewed_at is not None
        else None,
    }


def _matches_mapping(
    record: AchievementRecord, mapping: AchievementInputMapping
) -> bool:
    matches_type = (
        mapping.achievement_type is None
        or record.achievement_type == mapping.achievement_type
    )
    return matches_type and (mapping.level is None or record.level == mapping.level)


def build_achievement_context(
    records: list[AchievementRecord], mappings: list[AchievementInputMapping]
) -> dict[str, int | float]:
    """Build workflow context from approved source rows without expressions."""
    context: dict[str, int | float] = {}
    for mapping in mappings:
        matching = [record for record in records if _matches_mapping(record, mapping)]
        if mapping.aggregation == "count":
            context[mapping.context_key] = len(matching)
            continue
        total = 0.0
        for record in matching:
            assert mapping.payload_key is not None  # Guaranteed by Pydantic schema.
            value = record.payload.get(mapping.payload_key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise APIError(
                    status_code=422,
                    code="ACHIEVEMENT_MAPPING_VALUE_INVALID",
                    message=(
                        "approved achievement payload does not contain a numeric value"
                    ),
                    details={
                        "achievement_id": record.id,
                        "context_key": mapping.context_key,
                        "payload_key": mapping.payload_key,
                    },
                )
            total += float(value)
        context[mapping.context_key] = total
    return context


def _group_by_teacher(
    records: list[AchievementRecord], *, requested_teacher_ids: list[str]
) -> dict[str, list[AchievementRecord]]:
    grouped: dict[str, list[AchievementRecord]] = defaultdict(list)
    for record in records:
        grouped[record.teacher_id].append(record)
    missing_teachers = sorted(set(requested_teacher_ids) - set(grouped))
    if missing_teachers:
        raise APIError(
            status_code=409,
            code="NO_APPROVED_ACHIEVEMENTS",
            message=(
                "one or more requested teachers have no approved achievements in scope"
            ),
            details={"teacher_ids": missing_teachers},
        )
    for teacher_id, teacher_records in grouped.items():
        if len({record.department_id for record in teacher_records}) != 1:
            raise APIError(
                status_code=409,
                code="TEACHER_DEPARTMENT_AMBIGUOUS",
                message="a teacher has approved achievements in multiple departments",
                details={"teacher_id": teacher_id},
            )
    return dict(grouped)


def _result_total(workflow_run: WorkflowRun, *, result_node_key: str) -> float:
    result_data = workflow_run.result_data
    node_output = (
        result_data.get(result_node_key) if isinstance(result_data, dict) else None
    )
    amount = node_output.get("amount") if isinstance(node_output, dict) else None
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise APIError(
            status_code=409,
            code="FORMAL_RESULT_NODE_INVALID",
            message="configured result node does not contain a numeric amount",
            details={"result_node_key": result_node_key},
        )
    return float(amount)


async def _next_result_version(
    session: AsyncSession, *, period_id: str, teacher_id: str
) -> int:
    latest = await session.scalar(
        select(func.max(FormalCalculationResult.result_version)).where(
            FormalCalculationResult.period_id == period_id,
            FormalCalculationResult.teacher_id == teacher_id,
        )
    )
    return int(latest or 0) + 1


async def _save_result_sources(
    session: AsyncSession,
    *,
    result: FormalCalculationResult,
    records: list[AchievementRecord],
) -> None:
    now = _now()
    session.add_all(
        [
            FormalCalculationResultSource(
                result_id=result.id,
                achievement_id=record.id,
                achievement_snapshot=_achievement_snapshot(record),
                created_at=now,
            )
            for record in records
        ]
    )


async def start_formal_calculation_batch(
    session: AsyncSession,
    *,
    request: CreateFormalCalculationBatchRequest,
    user: User,
) -> FormalCalculationBatch:
    """Run one immutable workflow per teacher and retain a new result version."""
    workflow = await get_workflow_definition(session, workflow_id=request.workflow_id)
    if workflow.status != WorkflowStatus.ACTIVE:
        raise APIError(
            status_code=409,
            code="WORKFLOW_NOT_ACTIVE",
            message="only active workflows can be used for formal calculation",
            details={"status": workflow.status},
        )
    nodes = await list_workflow_nodes(session, workflow_id=workflow.id)
    if request.result_node_key not in {node.node_key for node in nodes}:
        raise APIError(
            status_code=422,
            code="FORMAL_RESULT_NODE_NOT_FOUND",
            message="result_node_key is not a node in the selected workflow",
            details={"result_node_key": request.result_node_key},
        )
    source_records = await list_approved_for_calculation(
        session,
        department_id=request.department_id,
        teacher_ids=request.teacher_ids or None,
        occurred_from=request.occurred_from,
        occurred_to=request.occurred_to,
        limit=10_000,
    )
    if not source_records:
        raise APIError(
            status_code=409,
            code="NO_APPROVED_ACHIEVEMENTS",
            message="no approved achievements match the requested batch scope",
        )
    grouped_records = _group_by_teacher(
        source_records, requested_teacher_ids=request.teacher_ids
    )
    mappings = request.input_mappings
    contexts = {
        teacher_id: build_achievement_context(records, mappings)
        for teacher_id, records in grouped_records.items()
    }

    now = _now()
    batch = FormalCalculationBatch(
        period_id=request.period_id,
        occurred_from=request.occurred_from,
        occurred_to=request.occurred_to,
        department_id=request.department_id,
        teacher_ids=request.teacher_ids,
        workflow_id=workflow.id,
        workflow_snapshot=_workflow_snapshot(workflow, nodes=nodes),
        input_mappings=[mapping.model_dump(mode="json") for mapping in mappings],
        result_node_key=request.result_node_key,
        status=FormalCalculationBatchStatus.RUNNING,
        created_by_user_id=user.id,
        created_at=now,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="FORMAL_CALCULATION_BATCH_STARTED",
        resource_type="formal_calculation_batch",
        resource_id=batch.id,
        details={
            "period_id": batch.period_id,
            "workflow": batch.workflow_snapshot,
            "teacher_count": len(grouped_records),
        },
    )

    failed_teacher_ids: list[str] = []
    for teacher_id, records in grouped_records.items():
        representative = records[0]
        workflow_run: WorkflowRun | None = None
        result_data: dict[str, Any] | None = None
        error_code: str | None = None
        error_message: str | None = None
        error_details: dict[str, Any] | None = None
        total_amount: float | None = None
        try:
            workflow_run, _ = await start_workflow_run(
                session,
                workflow_id=workflow.id,
                request=StartWorkflowRunRequest(
                    period_id=request.period_id,
                    context=contexts[teacher_id],
                ),
                user=user,
                run_mode=WorkflowRunMode.FORMAL,
            )
            result_data = workflow_run.result_data
            if workflow_run.status != "success":
                error_code = workflow_run.error_code or "WORKFLOW_RUN_FAILED"
                error_message = workflow_run.error_message or "workflow run failed"
                error_details = workflow_run.error_details
            else:
                total_amount = _result_total(
                    workflow_run, result_node_key=request.result_node_key
                )
        except APIError as error:
            error_code, error_message, error_details = _error_snapshot(error)
        except Exception:
            error_code = "FORMAL_CALCULATION_UNEXPECTED_ERROR"
            error_message = "formal calculation failed unexpectedly"

        finished_at = _now()
        if error_code is not None:
            failed_teacher_ids.append(teacher_id)
        result = FormalCalculationResult(
            batch_id=batch.id,
            teacher_id=teacher_id,
            teacher_name=representative.teacher_name,
            department_id=representative.department_id,
            period_id=request.period_id,
            result_version=await _next_result_version(
                session, period_id=request.period_id, teacher_id=teacher_id
            ),
            workflow_run_id=workflow_run.id if workflow_run is not None else None,
            status=(
                FormalCalculationResultStatus.FAILED
                if error_code is not None
                else FormalCalculationResultStatus.SUCCESS
            ),
            total_amount=total_amount,
            result_data=result_data,
            error_code=error_code,
            error_message=error_message,
            error_details=error_details,
            created_at=finished_at,
            finished_at=finished_at,
        )
        session.add(result)
        await session.flush()
        await _save_result_sources(session, result=result, records=records)
        await session.commit()

    batch.finished_at = _now()
    if failed_teacher_ids:
        batch.status = FormalCalculationBatchStatus.FAILED
        batch.error_code = "FORMAL_CALCULATION_PARTIAL_FAILURE"
        batch.error_message = "one or more teachers could not be calculated"
        batch.error_details = {"teacher_ids": failed_teacher_ids}
    else:
        batch.status = FormalCalculationBatchStatus.PENDING_REVIEW
    await session.commit()
    await session.refresh(batch)
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="FORMAL_CALCULATION_BATCH_FINISHED",
        resource_type="formal_calculation_batch",
        resource_id=batch.id,
        details={
            "status": batch.status,
            "failed_teacher_ids": failed_teacher_ids,
            "result_count": len(grouped_records),
        },
    )
    return batch


async def get_formal_calculation_batch(
    session: AsyncSession, *, batch_id: str
) -> FormalCalculationBatch:
    batch = await session.get(FormalCalculationBatch, batch_id)
    if batch is None:
        raise APIError(
            status_code=404,
            code="FORMAL_CALCULATION_BATCH_NOT_FOUND",
            message="formal calculation batch was not found",
        )
    return batch


async def list_formal_calculation_batches(
    session: AsyncSession,
    *,
    period_id: str | None = None,
    status: FormalCalculationBatchStatus | None = None,
    limit: int = 100,
) -> list[FormalCalculationBatch]:
    statement = select(FormalCalculationBatch)
    if period_id is not None:
        statement = statement.where(FormalCalculationBatch.period_id == period_id)
    if status is not None:
        statement = statement.where(FormalCalculationBatch.status == status)
    statement = statement.order_by(
        FormalCalculationBatch.created_at.desc(), FormalCalculationBatch.id
    ).limit(limit)
    return list((await session.scalars(statement)).all())


async def list_formal_calculation_results(
    session: AsyncSession,
    *,
    batch_id: str | None = None,
    period_id: str | None = None,
    teacher_id: str | None = None,
    status: FormalCalculationResultStatus | None = None,
    limit: int = 100,
) -> list[FormalCalculationResult]:
    statement = select(FormalCalculationResult)
    if batch_id is not None:
        statement = statement.where(FormalCalculationResult.batch_id == batch_id)
    if period_id is not None:
        statement = statement.where(FormalCalculationResult.period_id == period_id)
    if teacher_id is not None:
        statement = statement.where(FormalCalculationResult.teacher_id == teacher_id)
    if status is not None:
        statement = statement.where(FormalCalculationResult.status == status)
    statement = statement.order_by(
        FormalCalculationResult.period_id,
        FormalCalculationResult.teacher_id,
        FormalCalculationResult.result_version.desc(),
    ).limit(limit)
    return list((await session.scalars(statement)).all())


def render_formal_result_csv(
    results: list[FormalCalculationResult],
    sources_by_result: dict[str, list[FormalCalculationResultSource]],
) -> str:
    """Render result and source detail without exposing unapproved source data."""
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "batch_id",
            "period_id",
            "teacher_id",
            "teacher_name",
            "department_id",
            "result_version",
            "total_amount",
            "workflow_run_id",
            "achievement_id",
            "achievement_type",
            "achievement_level",
            "achievement_occurred_at",
            "achievement_source",
            "achievement_source_record_id",
        ],
    )
    writer.writeheader()
    for result in results:
        sources = sources_by_result.get(result.id, [])
        common = {
            "batch_id": result.batch_id,
            "period_id": result.period_id,
            "teacher_id": result.teacher_id,
            "teacher_name": result.teacher_name,
            "department_id": result.department_id,
            "result_version": result.result_version,
            "total_amount": result.total_amount,
            "workflow_run_id": result.workflow_run_id or "",
        }
        if not sources:
            writer.writerow(common)
            continue
        for source in sources:
            snapshot = source.achievement_snapshot
            writer.writerow(
                {
                    **common,
                    "achievement_id": source.achievement_id,
                    "achievement_type": snapshot.get("achievement_type", ""),
                    "achievement_level": snapshot.get("level", ""),
                    "achievement_occurred_at": snapshot.get("occurred_at", ""),
                    "achievement_source": snapshot.get("source", ""),
                    "achievement_source_record_id": snapshot.get(
                        "source_record_id", ""
                    )
                    or "",
                }
            )
    return output.getvalue()


async def list_result_sources(
    session: AsyncSession, *, result_id: str
) -> list[FormalCalculationResultSource]:
    statement = (
        select(FormalCalculationResultSource)
        .where(FormalCalculationResultSource.result_id == result_id)
        .order_by(
            FormalCalculationResultSource.created_at,
            FormalCalculationResultSource.id,
        )
    )
    return list((await session.scalars(statement)).all())


async def review_formal_calculation_batch(
    session: AsyncSession, *, batch_id: str, user: User
) -> FormalCalculationBatch:
    result = await session.execute(
        select(FormalCalculationBatch)
        .where(FormalCalculationBatch.id == batch_id)
        .with_for_update()
    )
    batch = result.scalar_one_or_none()
    if batch is None:
        raise APIError(
            status_code=404,
            code="FORMAL_CALCULATION_BATCH_NOT_FOUND",
            message="formal calculation batch was not found",
        )
    if batch.status != FormalCalculationBatchStatus.PENDING_REVIEW:
        raise APIError(
            status_code=409,
            code="FORMAL_CALCULATION_BATCH_NOT_REVIEWABLE",
            message="only a successful batch pending review can be confirmed",
            details={"status": batch.status},
        )
    batch.status = FormalCalculationBatchStatus.REVIEWED
    batch.reviewed_by_user_id = user.id
    batch.reviewed_at = _now()
    await session.commit()
    await session.refresh(batch)
    await write_audit_event(
        session,
        actor_user_id=user.id,
        event_type="FORMAL_CALCULATION_BATCH_REVIEWED",
        resource_type="formal_calculation_batch",
        resource_id=batch.id,
        details={"period_id": batch.period_id},
    )
    return batch
