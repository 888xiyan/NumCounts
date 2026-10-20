import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.api.v1.workflows import create_workflow_run, get_run
from app.core.errors import APIError
from app.models.user import User, UserRole
from app.models.workflow import WorkflowRun, WorkflowRunMode, WorkflowRunStatus
from app.schemas.workflows import StartWorkflowRunRequest
from app.services.member_service import (
    list_member_formal_results,
    require_teacher_id,
)


def _member(*, teacher_id: str | None) -> User:
    now = datetime.now(UTC)
    return User(
        id="member-1",
        username="member",
        teacher_id=teacher_id,
        password_hash="not-used-in-this-test",
        role=UserRole.USER,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_member_formal_access_requires_explicit_teacher_profile() -> None:
    with pytest.raises(APIError) as error:
        require_teacher_id(_member(teacher_id=None))

    assert error.value.detail["code"] == "TEACHER_PROFILE_NOT_LINKED"
    assert require_teacher_id(_member(teacher_id="teacher-001")) == "teacher-001"


def test_workflow_run_request_cannot_choose_a_persistence_mode() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StartWorkflowRunRequest.model_validate(
            {"context": {}, "run_mode": "formal"}
        )


def test_member_workflow_execution_is_forced_to_trial_mode() -> None:
    captured: dict[str, object] = {}

    async def fake_start(
        *args: object, **kwargs: object
    ) -> tuple[object, list[object]]:
        captured.update(kwargs)
        return object(), []

    with (
        patch("app.api.v1.workflows.start_workflow_run", side_effect=fake_start),
        patch(
            "app.api.v1.workflows._run_response",
            new=AsyncMock(return_value="member-trial-response"),
        ),
    ):
        response = asyncio.run(
            create_workflow_run(
                "workflow-1",
                StartWorkflowRunRequest(context={}),
                session=object(),  # type: ignore[arg-type]
                user=_member(teacher_id="teacher-001"),
            )
        )

    assert response == "member-trial-response"
    assert captured["run_mode"] == WorkflowRunMode.MEMBER_TRIAL


def test_member_cannot_read_another_users_or_formal_workflow_run() -> None:
    now = datetime.now(UTC)
    run = WorkflowRun(
        id="formal-run-1",
        workflow_id="workflow-1",
        workflow_key="performance",
        workflow_version="1.0.0",
        context={},
        run_mode=WorkflowRunMode.FORMAL,
        status=WorkflowRunStatus.SUCCESS,
        requested_by_user_id="admin-1",
        started_at=now,
        finished_at=now,
    )

    with patch(
        "app.api.v1.workflows.get_workflow_run",
        new=AsyncMock(return_value=run),
    ):
        with pytest.raises(APIError) as error:
            asyncio.run(
                get_run(
                    run.id,
                    session=object(),  # type: ignore[arg-type]
                    user=_member(teacher_id="teacher-001"),
                )
            )

    assert error.value.detail["code"] == "WORKFLOW_RUN_NOT_FOUND"


def test_member_formal_result_query_is_bound_to_teacher_and_reviewed_results() -> None:
    class ScalarResult:
        def all(self) -> list[object]:
            return []

    class CapturingSession:
        statement: object | None = None

        async def scalars(self, statement: object) -> ScalarResult:
            self.statement = statement
            return ScalarResult()

    session = CapturingSession()
    results = asyncio.run(
        list_member_formal_results(
            session,  # type: ignore[arg-type]
            teacher_id="teacher-001",
            period_id="2026-spring",
            limit=50,
        )
    )

    assert results == []
    assert session.statement is not None
    compiled = session.statement.compile()  # type: ignore[union-attr]
    assert "teacher-001" in compiled.params.values()
    assert "2026-spring" in compiled.params.values()
    assert "success" in compiled.params.values()
    assert "reviewed" in compiled.params.values()
