"""Operator workflow definitions and their synchronous MVP execution loop."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.calculation import CalculationRecord
from app.models.user import User
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowNodeRunStatus,
    WorkflowRun,
    WorkflowRunNode,
    WorkflowRunStatus,
    WorkflowStatus,
)
from app.schemas.records import CreateRecordRequest, RegisteredFunctionSpec
from app.schemas.workflows import (
    AggregateWorkflowNodeConfig,
    ContextInputBinding,
    CreateWorkflowDefinitionRequest,
    LiteralInputBinding,
    PluginWorkflowNodeConfig,
    PluginWorkflowNodeDefinition,
    StartWorkflowRunRequest,
)
from app.services.calculation_service import (
    create_record,
    create_record_from_plugin_snapshot,
    execute_record,
)
from app.services.plugin_service import resolve_enabled_plugin_snapshot


def _now() -> datetime:
    return datetime.now(UTC)


def _error_snapshot(error: APIError) -> dict[str, Any]:
    detail = error.detail
    if isinstance(detail, dict):
        return {
            "code": detail.get("code", "WORKFLOW_NODE_FAILED"),
            "message": detail.get("message", "workflow node failed"),
            "details": detail.get("details"),
        }
    return {"code": "WORKFLOW_NODE_FAILED", "message": str(detail)}


def _ensure_json_object(value: dict[str, Any], *, field: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise APIError(
            status_code=422,
            code="INVALID_WORKFLOW_CONTEXT",
            message=f"{field} must contain only JSON values",
        ) from error


def resolve_input_bindings(
    config: PluginWorkflowNodeConfig, context: dict[str, Any]
) -> dict[str, Any]:
    """Resolve only explicit top-level context keys or JSON literals.

    Deliberately avoiding an expression language keeps workflow configuration
    operator friendly and prevents it from becoming another code surface.
    """
    resolved: dict[str, Any] = {}
    for field_name, binding in config.input_bindings.items():
        if isinstance(binding, ContextInputBinding):
            if binding.key not in context:
                raise APIError(
                    status_code=422,
                    code="WORKFLOW_CONTEXT_VALUE_MISSING",
                    message="workflow context does not contain a required value",
                    details={"field": field_name, "context_key": binding.key},
                )
            resolved[field_name] = context[binding.key]
        elif isinstance(binding, LiteralInputBinding):
            resolved[field_name] = binding.value
        else:  # Defensive guard for future binding kinds.
            raise APIError(
                status_code=422,
                code="INVALID_WORKFLOW_INPUT_BINDING",
                message="workflow node contains an unsupported input binding",
                details={"field": field_name},
            )
    _ensure_json_object(resolved, field="resolved workflow input")
    return resolved


async def get_workflow_definition(
    session: AsyncSession, *, workflow_id: str
) -> WorkflowDefinition:
    workflow = await session.get(WorkflowDefinition, workflow_id)
    if workflow is None:
        raise APIError(
            status_code=404,
            code="WORKFLOW_NOT_FOUND",
            message="workflow was not found",
        )
    return workflow


async def list_workflow_nodes(
    session: AsyncSession, *, workflow_id: str
) -> list[WorkflowNode]:
    statement = (
        select(WorkflowNode)
        .where(WorkflowNode.workflow_id == workflow_id)
        .order_by(WorkflowNode.position)
    )
    return list((await session.scalars(statement)).all())


async def create_workflow_definition(
    session: AsyncSession, *, request: CreateWorkflowDefinitionRequest
) -> tuple[WorkflowDefinition, list[WorkflowNode]]:
    """Create an immutable draft and freeze plugin versions in its nodes."""
    now = _now()
    workflow = WorkflowDefinition(
        workflow_key=request.workflow_key,
        version=request.version,
        name=request.name,
        description=request.description,
        status=WorkflowStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
    session.add(workflow)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise APIError(
            status_code=409,
            code="WORKFLOW_VERSION_EXISTS",
            message="a workflow with the same key and version already exists",
            details={"workflow_key": request.workflow_key, "version": request.version},
        ) from error

    nodes: list[WorkflowNode] = []
    try:
        for position, node_definition in enumerate(request.nodes, start=1):
            plugin_snapshot: dict[str, Any] | None = None
            if isinstance(node_definition, PluginWorkflowNodeDefinition):
                plugin_snapshot = await resolve_enabled_plugin_snapshot(
                    session, plugin_id=node_definition.config.plugin_id
                )
            node = WorkflowNode(
                workflow_id=workflow.id,
                node_key=node_definition.node_key,
                node_type=node_definition.node_type,
                position=position,
                config=node_definition.config.model_dump(),
                plugin_snapshot=plugin_snapshot,
                created_at=now,
                updated_at=now,
            )
            nodes.append(node)
            session.add(node)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(workflow)
    return workflow, nodes


async def list_workflows(
    session: AsyncSession, *, status: WorkflowStatus | None = None
) -> list[WorkflowDefinition]:
    statement = select(WorkflowDefinition)
    if status is not None:
        statement = statement.where(WorkflowDefinition.status == status)
    statement = statement.order_by(
        WorkflowDefinition.workflow_key, WorkflowDefinition.version
    )
    return list((await session.scalars(statement)).all())


async def set_workflow_status(
    session: AsyncSession, *, workflow_id: str, active: bool
) -> WorkflowDefinition:
    workflow = await get_workflow_definition(session, workflow_id=workflow_id)
    workflow.status = WorkflowStatus.ACTIVE if active else WorkflowStatus.DISABLED
    workflow.updated_at = _now()
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def _create_run_node(
    session: AsyncSession, *, workflow_run: WorkflowRun, node: WorkflowNode
) -> WorkflowRunNode:
    run_node = WorkflowRunNode(
        workflow_run_id=workflow_run.id,
        workflow_node_id=node.id,
        node_key=node.node_key,
        node_type=node.node_type,
        status=WorkflowNodeRunStatus.RUNNING,
        started_at=_now(),
    )
    session.add(run_node)
    await session.commit()
    await session.refresh(run_node)
    return run_node


async def _mark_run_node_success(
    session: AsyncSession,
    *,
    run_node: WorkflowRunNode,
    record: CalculationRecord,
    input_snapshot: dict[str, Any],
) -> None:
    run_node.status = WorkflowNodeRunStatus.SUCCESS
    run_node.calculation_record_id = record.id
    run_node.input_snapshot = input_snapshot
    run_node.output_snapshot = record.output_data
    run_node.finished_at = _now()
    await session.commit()


async def _mark_run_node_failed(
    session: AsyncSession,
    *,
    run_node: WorkflowRunNode,
    error: dict[str, Any],
    record: CalculationRecord | None = None,
    input_snapshot: dict[str, Any] | None = None,
) -> None:
    run_node.status = WorkflowNodeRunStatus.FAILED
    run_node.calculation_record_id = record.id if record is not None else None
    run_node.input_snapshot = input_snapshot
    run_node.output_snapshot = record.output_data if record is not None else None
    run_node.error_snapshot = error
    run_node.finished_at = _now()
    await session.commit()


async def _mark_remaining_nodes_skipped(
    session: AsyncSession,
    *,
    workflow_run: WorkflowRun,
    nodes: list[WorkflowNode],
) -> None:
    now = _now()
    for node in nodes:
        session.add(
            WorkflowRunNode(
                workflow_run_id=workflow_run.id,
                workflow_node_id=node.id,
                node_key=node.node_key,
                node_type=node.node_type,
                status=WorkflowNodeRunStatus.SKIPPED,
                error_snapshot={
                    "code": "UPSTREAM_NODE_FAILED",
                    "message": "workflow stopped before this node could run",
                },
                finished_at=now,
            )
        )
    await session.commit()


def _aggregate_amounts(
    config: AggregateWorkflowNodeConfig, outputs: dict[str, dict[str, Any]]
) -> list[float]:
    amounts: list[float] = []
    for node_key in config.source_node_keys:
        output = outputs.get(node_key)
        amount = output.get("amount") if isinstance(output, dict) else None
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise APIError(
                status_code=409,
                code="WORKFLOW_AGGREGATE_INPUT_INVALID",
                message="aggregate source node does not have a numeric amount output",
                details={"source_node_key": node_key},
            )
        amounts.append(float(amount))
    return amounts


async def start_workflow_run(
    session: AsyncSession,
    *,
    workflow_id: str,
    request: StartWorkflowRunRequest,
    user: User,
) -> tuple[WorkflowRun, list[WorkflowRunNode]]:
    """Run one immutable workflow definition sequentially for an operator."""
    _ensure_json_object(request.context, field="workflow context")
    workflow = await get_workflow_definition(session, workflow_id=workflow_id)
    if workflow.status != WorkflowStatus.ACTIVE:
        raise APIError(
            status_code=409,
            code="WORKFLOW_NOT_ACTIVE",
            message="only active workflows can be started",
            details={"status": workflow.status},
        )
    nodes = await list_workflow_nodes(session, workflow_id=workflow.id)
    now = _now()
    workflow_run = WorkflowRun(
        workflow_id=workflow.id,
        workflow_key=workflow.workflow_key,
        workflow_version=workflow.version,
        period_id=request.period_id,
        context=request.context,
        status=WorkflowRunStatus.RUNNING,
        requested_by_user_id=user.id,
        started_at=now,
    )
    session.add(workflow_run)
    await session.commit()
    await session.refresh(workflow_run)

    outputs: dict[str, dict[str, Any]] = {}
    run_nodes: list[WorkflowRunNode] = []
    for index, node in enumerate(nodes):
        run_node = await _create_run_node(
            session, workflow_run=workflow_run, node=node
        )
        run_nodes.append(run_node)
        record: CalculationRecord | None = None
        node_input: dict[str, Any] | None = None
        try:
            if node.node_type == "plugin":
                config = PluginWorkflowNodeConfig.model_validate(node.config)
                if node.plugin_snapshot is None:
                    raise APIError(
                        status_code=409,
                        code="INVALID_PLUGIN_SNAPSHOT",
                        message="workflow plugin node has no frozen plugin version",
                    )
                bound_input = resolve_input_bindings(config, request.context)
                node_input = {**node.plugin_snapshot["input_defaults"], **bound_input}
                record = await create_record_from_plugin_snapshot(
                    session,
                    table_name=config.table_name,
                    period_id=request.period_id,
                    input_data=node_input,
                    plugin_snapshot=node.plugin_snapshot,
                    requested_by_user_id=user.id,
                    workflow_run_id=workflow_run.id,
                )
            elif node.node_type == "aggregate":
                config = AggregateWorkflowNodeConfig.model_validate(node.config)
                node_input = {"amounts": _aggregate_amounts(config, outputs)}
                record, _ = await create_record(
                    session,
                    request=CreateRecordRequest(
                        table_name=config.table_name,
                        period_id=request.period_id,
                        input=node_input,
                        function=RegisteredFunctionSpec(
                            kind="registered",
                            name="aggregate_amounts",
                            version="1.0.0",
                        ),
                    ),
                    idempotency_key=str(uuid.uuid4()),
                    requested_by_user_id=user.id,
                    workflow_run_id=workflow_run.id,
                )
            else:
                raise APIError(
                    status_code=409,
                    code="INVALID_WORKFLOW_NODE",
                    message="workflow contains an unsupported node type",
                    details={"node_type": node.node_type},
                )

            record = await execute_record(session, record_id=record.id)
            if record.status != "success":
                raise APIError(
                    status_code=409,
                    code=record.error_code or "CALCULATION_FAILED",
                    message=record.error_message or "calculation record failed",
                    details=record.error_details,
                )
            output = record.output_data or {}
            outputs[node.node_key] = output
            await _mark_run_node_success(
                session,
                run_node=run_node,
                record=record,
                input_snapshot=node_input or {},
            )
        except APIError as error:
            error_snapshot = _error_snapshot(error)
            await _mark_run_node_failed(
                session,
                run_node=run_node,
                error=error_snapshot,
                record=record,
                input_snapshot=node_input,
            )
            await _mark_remaining_nodes_skipped(
                session,
                workflow_run=workflow_run,
                nodes=nodes[index + 1 :],
            )
            workflow_run.status = WorkflowRunStatus.FAILED
            workflow_run.error_code = error_snapshot["code"]
            workflow_run.error_message = error_snapshot["message"]
            workflow_run.error_details = error_snapshot.get("details")
            workflow_run.finished_at = _now()
            await session.commit()
            return workflow_run, await list_workflow_run_nodes(
                session, workflow_run_id=workflow_run.id
            )

    workflow_run.status = WorkflowRunStatus.SUCCESS
    workflow_run.result_data = outputs
    workflow_run.finished_at = _now()
    await session.commit()
    return workflow_run, await list_workflow_run_nodes(
        session, workflow_run_id=workflow_run.id
    )


async def get_workflow_run(
    session: AsyncSession, *, workflow_run_id: str
) -> WorkflowRun:
    workflow_run = await session.get(WorkflowRun, workflow_run_id)
    if workflow_run is None:
        raise APIError(
            status_code=404,
            code="WORKFLOW_RUN_NOT_FOUND",
            message="workflow run was not found",
        )
    return workflow_run


async def list_workflow_run_nodes(
    session: AsyncSession, *, workflow_run_id: str
) -> list[WorkflowRunNode]:
    statement = (
        select(WorkflowRunNode)
        .join(WorkflowNode, WorkflowRunNode.workflow_node_id == WorkflowNode.id)
        .where(WorkflowRunNode.workflow_run_id == workflow_run_id)
        .order_by(WorkflowNode.position)
    )
    return list((await session.scalars(statement)).all())


async def list_workflow_runs(
    session: AsyncSession, *, workflow_id: str, limit: int
) -> list[WorkflowRun]:
    await get_workflow_definition(session, workflow_id=workflow_id)
    statement = (
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.started_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())
