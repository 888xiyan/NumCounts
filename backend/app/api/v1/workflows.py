from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.db.session import get_session
from app.models.user import User, UserRole
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRun,
    WorkflowRunNode,
    WorkflowStatus,
)
from app.schemas.workflows import (
    CreateWorkflowDefinitionRequest,
    StartWorkflowRunRequest,
    WorkflowDefinitionListResponse,
    WorkflowDefinitionResponse,
    WorkflowNodeResponse,
    WorkflowRunListResponse,
    WorkflowRunNodeResponse,
    WorkflowRunResponse,
)
from app.services.workflow_service import (
    create_workflow_definition,
    get_workflow_definition,
    get_workflow_run,
    list_workflow_nodes,
    list_workflow_run_nodes,
    list_workflow_runs,
    list_workflows,
    set_workflow_status,
    start_workflow_run,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])
run_router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])


def _node_response(node: WorkflowNode) -> WorkflowNodeResponse:
    return WorkflowNodeResponse(
        id=node.id,
        node_key=node.node_key,
        node_type=node.node_type,
        position=node.position,
        config=node.config,
        plugin=node.plugin_snapshot,
    )


async def _workflow_response(
    session: AsyncSession, workflow: WorkflowDefinition
) -> WorkflowDefinitionResponse:
    return WorkflowDefinitionResponse(
        id=workflow.id,
        workflow_key=workflow.workflow_key,
        version=workflow.version,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        nodes=[
            _node_response(node)
            for node in await list_workflow_nodes(session, workflow_id=workflow.id)
        ],
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


def _run_node_response(node: WorkflowRunNode) -> WorkflowRunNodeResponse:
    error = node.error_snapshot
    return WorkflowRunNodeResponse(
        id=node.id,
        node_key=node.node_key,
        node_type=node.node_type,
        status=node.status,
        calculation_record_id=node.calculation_record_id,
        input_snapshot=node.input_snapshot,
        output_snapshot=node.output_snapshot,
        error=error,
        started_at=node.started_at,
        finished_at=node.finished_at,
    )


async def _run_response(
    session: AsyncSession, workflow_run: WorkflowRun
) -> WorkflowRunResponse:
    error: dict[str, Any] | None = None
    if workflow_run.error_code is not None:
        error = {
            "code": workflow_run.error_code,
            "message": workflow_run.error_message or "workflow run failed",
            "details": workflow_run.error_details,
        }
    return WorkflowRunResponse(
        id=workflow_run.id,
        workflow_id=workflow_run.workflow_id,
        workflow_key=workflow_run.workflow_key,
        workflow_version=workflow_run.workflow_version,
        period_id=workflow_run.period_id,
        context=workflow_run.context,
        status=workflow_run.status,
        result=workflow_run.result_data,
        error=error,
        requested_by_user_id=workflow_run.requested_by_user_id,
        started_at=workflow_run.started_at,
        finished_at=workflow_run.finished_at,
        nodes=[
            _run_node_response(node)
            for node in await list_workflow_run_nodes(
                session, workflow_run_id=workflow_run.id
            )
        ],
    )


@router.post(
    "", response_model=WorkflowDefinitionResponse, status_code=status.HTTP_201_CREATED
)
async def create_workflow(
    request: CreateWorkflowDefinitionRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowDefinitionResponse:
    workflow, _ = await create_workflow_definition(session, request=request)
    return await _workflow_response(session, workflow)


@router.get("", response_model=WorkflowDefinitionListResponse)
async def list_workflow_definitions(
    status_filter: WorkflowStatus | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowDefinitionListResponse:
    workflows = await list_workflows(session, status=status_filter)
    return WorkflowDefinitionListResponse(
        data=[await _workflow_response(session, workflow) for workflow in workflows]
    )


@router.get("/{workflow_id}", response_model=WorkflowDefinitionResponse)
async def get_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowDefinitionResponse:
    return await _workflow_response(
        session, await get_workflow_definition(session, workflow_id=workflow_id)
    )


@router.post("/{workflow_id}/activate", response_model=WorkflowDefinitionResponse)
async def activate_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowDefinitionResponse:
    workflow = await set_workflow_status(
        session, workflow_id=workflow_id, active=True
    )
    return await _workflow_response(session, workflow)


@router.post("/{workflow_id}/disable", response_model=WorkflowDefinitionResponse)
async def disable_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowDefinitionResponse:
    workflow = await set_workflow_status(
        session, workflow_id=workflow_id, active=False
    )
    return await _workflow_response(session, workflow)


@router.post(
    "/{workflow_id}/runs",
    response_model=WorkflowRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_run(
    workflow_id: str,
    request: StartWorkflowRunRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowRunResponse:
    workflow_run, _ = await start_workflow_run(
        session, workflow_id=workflow_id, request=request, user=user
    )
    return await _run_response(session, workflow_run)


@router.get("/{workflow_id}/runs", response_model=WorkflowRunListResponse)
async def list_runs(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowRunListResponse:
    runs = await list_workflow_runs(session, workflow_id=workflow_id, limit=limit)
    return WorkflowRunListResponse(
        data=[await _run_response(session, workflow_run) for workflow_run in runs]
    )


@run_router.get("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def get_run(
    workflow_run_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> WorkflowRunResponse:
    return await _run_response(
        session, await get_workflow_run(session, workflow_run_id=workflow_run_id)
    )
