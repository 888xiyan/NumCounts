from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.errors import APIError
from app.db.session import get_session
from app.models.user import User, UserRole
from app.models.workflow import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRun,
    WorkflowRunMode,
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
        run_mode=workflow_run.run_mode,
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
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> WorkflowDefinitionListResponse:
    if user.role == UserRole.USER:
        status_filter = WorkflowStatus.ACTIVE
    workflows = await list_workflows(session, status=status_filter)
    return WorkflowDefinitionListResponse(
        data=[await _workflow_response(session, workflow) for workflow in workflows]
    )


@router.get("/{workflow_id}", response_model=WorkflowDefinitionResponse)
async def get_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> WorkflowDefinitionResponse:
    workflow = await get_workflow_definition(session, workflow_id=workflow_id)
    if user.role == UserRole.USER and workflow.status != WorkflowStatus.ACTIVE:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORKFLOW_NOT_AVAILABLE",
            message="workflow is not available to members",
        )
    return await _workflow_response(session, workflow)


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
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> WorkflowRunResponse:
    workflow_run, _ = await start_workflow_run(
        session,
        workflow_id=workflow_id,
        request=request,
        user=user,
        run_mode=(
            WorkflowRunMode.MEMBER_TRIAL
            if user.role == UserRole.USER
            else WorkflowRunMode.OPERATOR
        ),
    )
    return await _run_response(session, workflow_run)


@router.get("/{workflow_id}/runs", response_model=WorkflowRunListResponse)
async def list_runs(
    workflow_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> WorkflowRunListResponse:
    runs = await list_workflow_runs(
        session,
        workflow_id=workflow_id,
        limit=limit,
        requested_by_user_id=user.id if user.role == UserRole.USER else None,
        run_mode=(
            WorkflowRunMode.MEMBER_TRIAL if user.role == UserRole.USER else None
        ),
    )
    return WorkflowRunListResponse(
        data=[await _run_response(session, workflow_run) for workflow_run in runs]
    )


@run_router.get("/{workflow_run_id}", response_model=WorkflowRunResponse)
async def get_run(
    workflow_run_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> WorkflowRunResponse:
    workflow_run = await get_workflow_run(session, workflow_run_id=workflow_run_id)
    if user.role == UserRole.USER and (
        workflow_run.requested_by_user_id != user.id
        or workflow_run.run_mode != WorkflowRunMode.MEMBER_TRIAL
    ):
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="WORKFLOW_RUN_NOT_FOUND",
            message="workflow run was not found",
        )
    return await _run_response(session, workflow_run)
