"""Opt-in acceptance against the configured, local MySQL database.

Run only when explicitly intended with the NUMCOUNTS_RUN_M8_ACCEPTANCE=1 flag.
The test creates uniquely named sample records and removes only those records.
"""

import asyncio
import os
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

if os.getenv("NUMCOUNTS_RUN_M8_ACCEPTANCE") != "1":
    pytest.skip(
        "set NUMCOUNTS_RUN_M8_ACCEPTANCE=1 to use local MySQL", allow_module_level=True
    )

import httpx
from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.functions.registry import _REGISTRY, RegisteredFunction
from app.main import app
from app.models.calculation import CalculationAttempt, CalculationRecord
from app.models.user import User, UserRole


class AcceptanceSpecialCaseInput(BaseModel):
    case_snapshot: dict[str, Any]
    materials: list[dict[str, Any]]


def _special_case_output(value: AcceptanceSpecialCaseInput) -> dict[str, Any]:
    form_data = value.case_snapshot["form_data"]
    return {
        "achievement_type": form_data["achievement_type"],
        "level": form_data["level"],
        "occurred_at": form_data["occurred_at"],
        "payload": form_data["payload"],
    }


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


_SPECIAL_FUNCTION_KEY = ("m8_acceptance_special_case", "1.0.0")
_SPECIAL_FUNCTION = RegisteredFunction(
    name=_SPECIAL_FUNCTION_KEY[0],
    version=_SPECIAL_FUNCTION_KEY[1],
    description="Deterministic test adapter for the special-case plugin contract.",
    input_model=AcceptanceSpecialCaseInput,
    output_schema={
        "type": "object",
        "required": ["achievement_type", "level", "occurred_at", "payload"],
    },
    handler=_special_case_output,
)


_COUNT_TABLES = (
    "users",
    "rule_plugins",
    "workflow_definitions",
    "workflow_nodes",
    "workflow_runs",
    "workflow_run_nodes",
    "calculation_records",
    "calculation_attempts",
    "achievement_records",
    "formal_calculation_batches",
    "formal_calculation_results",
    "formal_calculation_result_sources",
    "special_performance_cases",
    "special_performance_case_materials",
    "special_performance_case_events",
    "audit_events",
)


async def _table_counts() -> dict[str, int]:
    async with async_session_factory() as session:
        return {
            table: int(
                (
                    await session.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
                ).scalar_one()
            )
            for table in _COUNT_TABLES
        }


async def _cleanup_acceptance_data(
    *,
    marker: str,
    teacher_ids: list[str],
    usernames: list[str],
    plugin_keys: list[str],
    workflow_key: str,
) -> None:
    async with async_session_factory() as session:
        cases = await session.execute(
            text("SELECT id FROM special_performance_cases WHERE period_id=:marker"),
            {"marker": marker},
        )
        case_ids = list(cases.scalars().all())
        batches = await session.execute(
            text("SELECT id FROM formal_calculation_batches WHERE period_id=:marker"),
            {"marker": marker},
        )
        batch_ids = list(batches.scalars().all())
        users = await session.execute(
            text("SELECT id FROM users WHERE username IN :usernames").bindparams(
                bindparam("usernames", expanding=True)
            ),
            {"usernames": usernames},
        )
        user_ids = list(users.scalars().all())
        results = await session.execute(
            text("SELECT id FROM formal_calculation_results WHERE period_id=:marker"),
            {"marker": marker},
        )
        result_ids = list(results.scalars().all())
        records = await session.execute(
            text("SELECT id FROM calculation_records WHERE period_id=:marker"),
            {"marker": marker},
        )
        record_ids = list(records.scalars().all())
        runs = await session.execute(
            text("SELECT id FROM workflow_runs WHERE period_id=:marker"),
            {"marker": marker},
        )
        run_ids = list(runs.scalars().all())
        workflows = await session.execute(
            text(
                "SELECT id FROM workflow_definitions WHERE workflow_key=:workflow_key"
            ),
            {"workflow_key": workflow_key},
        )
        workflow_ids = list(workflows.scalars().all())
        plugins = await session.execute(
            text("SELECT id FROM rule_plugins WHERE plugin_key IN :keys").bindparams(
                bindparam("keys", expanding=True)
            ),
            {"keys": plugin_keys},
        )
        plugin_ids = list(plugins.scalars().all())
        achievements = await session.execute(
            text(
                "SELECT id FROM achievement_records "
                "WHERE teacher_id IN :teachers OR submitted_by_user_id IN :users"
            ).bindparams(
                bindparam("teachers", expanding=True),
                bindparam("users", expanding=True),
            ),
            {"teachers": teacher_ids, "users": user_ids},
        )
        achievement_ids = list(achievements.scalars().all())
        nodes = await session.execute(
            text("SELECT id FROM workflow_nodes WHERE workflow_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": workflow_ids},
        )
        node_ids = list(nodes.scalars().all())
        materials = await session.execute(
            text(
                "SELECT id FROM special_performance_case_materials "
                "WHERE case_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": case_ids},
        )
        material_ids = list(materials.scalars().all())
        events = await session.execute(
            text(
                "SELECT id FROM special_performance_case_events WHERE case_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": case_ids},
        )
        event_ids = list(events.scalars().all())
        attempts = await session.execute(
            text(
                "SELECT id FROM calculation_attempts WHERE record_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": record_ids},
        )
        attempt_ids = list(attempts.scalars().all())

        resource_ids = list(
            dict.fromkeys(
                case_ids
                + batch_ids
                + result_ids
                + record_ids
                + run_ids
                + workflow_ids
                + node_ids
                + plugin_ids
                + achievement_ids
                + material_ids
                + event_ids
                + attempt_ids
            )
        )
        if resource_ids or user_ids:
            await session.execute(
                text(
                    "DELETE FROM audit_events WHERE resource_id IN :resources "
                    "OR actor_user_id IN :actors "
                    "OR (event_type='FORMAL_CALCULATION_RESULTS_EXPORTED' "
                    "AND (JSON_UNQUOTE(JSON_EXTRACT(details, '$.period_id'))=:marker "
                    "OR JSON_UNQUOTE(JSON_EXTRACT(details, '$.batch_id')) IN :batches))"
                ).bindparams(
                    bindparam("resources", expanding=True),
                    bindparam("actors", expanding=True),
                    bindparam("batches", expanding=True),
                ),
                {
                    "resources": resource_ids,
                    "actors": user_ids,
                    "marker": marker,
                    "batches": batch_ids,
                },
            )

        async def delete_ids(table: str, column: str, ids: list[str]) -> None:
            if ids:
                await session.execute(
                    text(f"DELETE FROM `{table}` WHERE `{column}` IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": ids},
                )

        await delete_ids("special_performance_case_materials", "case_id", case_ids)
        await delete_ids("special_performance_case_events", "case_id", case_ids)
        await delete_ids("special_performance_cases", "id", case_ids)
        await delete_ids("formal_calculation_result_sources", "result_id", result_ids)
        await delete_ids("workflow_run_nodes", "workflow_run_id", run_ids)
        await delete_ids("calculation_attempts", "record_id", record_ids)
        await delete_ids("formal_calculation_results", "id", result_ids)
        await delete_ids("formal_calculation_batches", "id", batch_ids)
        await delete_ids("calculation_records", "id", record_ids)
        await delete_ids("workflow_runs", "id", run_ids)
        await delete_ids("workflow_nodes", "id", node_ids)
        await delete_ids("workflow_definitions", "id", workflow_ids)
        await delete_ids("achievement_records", "id", achievement_ids)
        await delete_ids("rule_plugins", "id", plugin_ids)
        await delete_ids("users", "id", user_ids)
        await session.commit()


def test_live_mysql_business_and_runtime_acceptance() -> None:
    url = make_url(settings.database_url)
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert url.database == "numcounts"

    async def acceptance() -> None:
        async with async_session_factory() as session:
            revision = await session.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            running_count = await session.scalar(
                text("SELECT COUNT(*) FROM calculation_records WHERE status='running'")
            )
        assert revision == "20261020_0011"
        assert running_count == 0, (
            "refuse recovery test while unrelated rows are running"
        )

        marker = f"m8accept{uuid.uuid4().hex[:12]}"
        workflow_key = f"{marker}_annual"
        plugin_keys = [f"{marker}_teaching", f"{marker}_special"]
        usernames = [f"{marker}_a", f"{marker}_b"]
        teacher_ids = [f"{marker}_teacher_a", f"{marker}_teacher_b"]
        department_id = f"{marker}_department"
        passwords = [uuid.uuid4().hex, uuid.uuid4().hex]
        baseline = await _table_counts()
        previous_special = _REGISTRY.get(_SPECIAL_FUNCTION_KEY)
        _REGISTRY[_SPECIAL_FUNCTION_KEY] = _SPECIAL_FUNCTION

        try:
            now = datetime.now(UTC)
            async with async_session_factory() as session:
                session.add_all(
                    [
                        User(
                            id=str(uuid.uuid4()),
                            username=usernames[index],
                            teacher_id=teacher_ids[index],
                            password_hash=hash_password(passwords[index]),
                            role=UserRole.USER,
                            is_active=True,
                            created_at=now,
                            updated_at=now,
                        )
                        for index in range(2)
                    ]
                )
                await session.commit()

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://numcounts.local",
                timeout=30,
            ) as client:
                live = await client.get("/api/v1/health/live")
                assert live.status_code == 200 and live.json()["status"] == "ok"
                ready = await client.get("/api/v1/health/ready")
                assert ready.status_code == 200 and ready.json()["status"] == "ready"

                admin_login = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": settings.seed_admin_username,
                        "password": settings.seed_admin_password,
                    },
                )
                assert admin_login.status_code == 200, admin_login.text
                admin_token = admin_login.json()["access_token"]
                admin_headers = {"Authorization": f"Bearer {admin_token}"}
                admin_me = await client.get("/api/v1/auth/me", headers=admin_headers)
                assert (
                    admin_me.status_code == 200 and admin_me.json()["role"] == "ADMIN"
                )

                member_headers: list[dict[str, str]] = []
                for username, password in zip(usernames, passwords, strict=True):
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"username": username, "password": password},
                    )
                    assert login.status_code == 200, login.text
                    token = login.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    me = await client.get("/api/v1/auth/me", headers=headers)
                    assert me.status_code == 200 and me.json()["role"] == "USER"
                    assert me.json()["teacher_id"] in teacher_ids
                    member_headers.append(headers)

                summary = await client.get(
                    "/api/v1/runtime/summary", headers=admin_headers
                )
                assert summary.status_code == 200
                assert {
                    "total_record_count",
                    "failed_record_count",
                    "oldest_pending_at",
                    "oldest_running_at",
                } <= summary.json().keys()
                denied_summary = await client.get(
                    "/api/v1/runtime/summary", headers=member_headers[0]
                )
                assert denied_summary.status_code == 403

                teaching_plugin_response = await client.post(
                    "/api/v1/rule-plugins",
                    headers=admin_headers,
                    json={
                        "plugin_key": plugin_keys[0],
                        "version": "1.0.0",
                        "name": "M8 acceptance teaching rule",
                        "function": {
                            "kind": "registered",
                            "name": "teaching_performance",
                            "version": "1.0.0",
                        },
                        "input_defaults": {"rate": 80, "quality_factor": 1},
                    },
                )
                assert teaching_plugin_response.status_code == 201, (
                    teaching_plugin_response.text
                )
                teaching_plugin_id = teaching_plugin_response.json()["id"]

                special_plugin_response = await client.post(
                    "/api/v1/rule-plugins",
                    headers=admin_headers,
                    json={
                        "plugin_key": plugin_keys[1],
                        "version": "1.0.0",
                        "name": "M8 acceptance special-case adapter",
                        "function": {
                            "kind": "registered",
                            "name": _SPECIAL_FUNCTION_KEY[0],
                            "version": _SPECIAL_FUNCTION_KEY[1],
                        },
                        "purpose": "special_case",
                    },
                )
                assert special_plugin_response.status_code == 201, (
                    special_plugin_response.text
                )
                special_plugin_id = special_plugin_response.json()["id"]

                for plugin_id in (teaching_plugin_id, special_plugin_id):
                    enabled = await client.post(
                        f"/api/v1/rule-plugins/{plugin_id}/enable",
                        headers=admin_headers,
                    )
                    assert (
                        enabled.status_code == 200
                        and enabled.json()["status"] == "enabled"
                    )

                today = date.today().isoformat()
                achievement_ids: list[str] = []
                for index, hours in enumerate((36, 10)):
                    declaration = await client.post(
                        "/api/v1/achievements/declarations",
                        headers=member_headers[index],
                        json={
                            "department_id": department_id,
                            "achievement_type": "teaching_workload",
                            "level": "undergraduate",
                            "occurred_at": today,
                            "payload": {"hours": hours},
                        },
                    )
                    assert declaration.status_code == 201, declaration.text
                    achievement_id = declaration.json()["id"]
                    achievement_ids.append(achievement_id)
                    assert declaration.json()["status"] == "pending_review"
                    review = await client.post(
                        f"/api/v1/achievements/{achievement_id}/review",
                        headers=admin_headers,
                        json={
                            "decision": "approve",
                            "comment": "M8 synthetic acceptance",
                        },
                    )
                    assert review.status_code == 200, review.text
                    assert review.json()["status"] == "approved"
                    eligible = await client.get(
                        "/api/v1/achievements/eligible", headers=member_headers[index]
                    )
                    assert eligible.status_code == 200
                    assert [row["id"] for row in eligible.json()["data"]] == [
                        achievement_id
                    ]

                workflow_response = await client.post(
                    "/api/v1/workflows",
                    headers=admin_headers,
                    json={
                        "workflow_key": workflow_key,
                        "version": "1.0.0",
                        "name": "M8 acceptance workflow",
                        "nodes": [
                            {
                                "node_key": "teaching",
                                "node_type": "plugin",
                                "config": {
                                    "plugin_id": teaching_plugin_id,
                                    "table_name": "teaching_results",
                                    "input_bindings": {
                                        "hours": {
                                            "kind": "context",
                                            "key": "approved_hours",
                                        }
                                    },
                                },
                            },
                            {
                                "node_key": "total",
                                "node_type": "aggregate",
                                "config": {
                                    "table_name": "performance_total",
                                    "source_node_keys": ["teaching"],
                                },
                            },
                        ],
                    },
                )
                assert workflow_response.status_code == 201, workflow_response.text
                workflow_id = workflow_response.json()["id"]
                activated = await client.post(
                    f"/api/v1/workflows/{workflow_id}/activate", headers=admin_headers
                )
                assert (
                    activated.status_code == 200
                    and activated.json()["status"] == "active"
                )

                trial = await client.post(
                    f"/api/v1/workflows/{workflow_id}/runs",
                    headers=member_headers[0],
                    json={"period_id": marker, "context": {"approved_hours": 36}},
                )
                assert trial.status_code == 201, trial.text
                assert trial.json()["run_mode"] == "member_trial"
                assert trial.json()["status"] == "success"
                assert trial.json()["result"]["total"]["amount"] == 2880
                hidden_trial = await client.get(
                    f"/workflow-runs/{trial.json()['id']}", headers=member_headers[1]
                )
                assert hidden_trial.status_code == 404

                batch_request = {
                    "period_id": marker,
                    "occurred_from": today,
                    "occurred_to": today,
                    "department_id": department_id,
                    "teacher_ids": teacher_ids,
                    "workflow_id": workflow_id,
                    "result_node_key": "total",
                    "input_mappings": [
                        {
                            "context_key": "approved_hours",
                            "aggregation": "sum",
                            "achievement_type": "teaching_workload",
                            "payload_key": "hours",
                        }
                    ],
                }

                async def create_and_confirm_batch(
                    expected: dict[str, float],
                ) -> dict[str, Any]:
                    response = await client.post(
                        "/api/v1/formal-calculation-batches",
                        headers=admin_headers,
                        json=batch_request,
                    )
                    assert response.status_code == 201, response.text
                    batch = response.json()
                    assert batch["status"] == "pending_review"
                    by_teacher = {
                        result["teacher_id"]: result for result in batch["results"]
                    }
                    assert set(by_teacher) == set(teacher_ids)
                    for teacher_id, amount in expected.items():
                        assert by_teacher[teacher_id]["status"] == "success"
                        assert by_teacher[teacher_id]["total_amount"] == amount
                        assert by_teacher[teacher_id]["sources"]
                    confirm = await client.post(
                        f"/api/v1/formal-calculation-batches/{batch['id']}/review",
                        headers=admin_headers,
                        json={"action": "confirm"},
                    )
                    assert confirm.status_code == 200, confirm.text
                    assert confirm.json()["status"] == "reviewed"
                    return batch

                first_batch = await create_and_confirm_batch(
                    {teacher_ids[0]: 2880, teacher_ids[1]: 800}
                )
                first_results = {
                    result["teacher_id"]: result for result in first_batch["results"]
                }
                for index in range(2):
                    own_results = await client.get(
                        f"/api/v1/me/formal-calculation-results?period_id={marker}",
                        headers=member_headers[index],
                    )
                    assert own_results.status_code == 200
                    rows = own_results.json()["data"]
                    assert {row["teacher_id"] for row in rows} == {teacher_ids[index]}
                    assert rows[0]["result_version"] == 1
                blocked_admin_list = await client.get(
                    f"/api/v1/formal-calculation-results?period_id={marker}",
                    headers=member_headers[0],
                )
                assert blocked_admin_list.status_code == 403
                member_export = await client.get(
                    f"/api/v1/me/formal-calculation-results/export?period_id={marker}",
                    headers=member_headers[0],
                )
                assert member_export.status_code == 200
                assert member_export.text.count("m8_acceptance") == 0

                case_response = await client.post(
                    "/api/v1/special-performance-cases",
                    headers=member_headers[0],
                    json={
                        "case_type": "appeal",
                        "title": "M8 synthetic appeal",
                        "original_result_id": first_results[teacher_ids[0]]["id"],
                        "form_data": {
                            "reason": "synthetic omitted workload",
                            "achievement_type": "teaching_workload",
                            "level": "undergraduate",
                            "occurred_at": today,
                            "payload": {"hours": 9},
                        },
                    },
                )
                assert case_response.status_code == 201, case_response.text
                case_id = case_response.json()["id"]
                material_content = f"synthetic M8 evidence {marker}\n".encode()
                material = await client.post(
                    f"/api/v1/special-performance-cases/{case_id}/materials/evidence",
                    params={"filename": "synthetic-evidence.txt"},
                    headers={**member_headers[0], "Content-Type": "text/plain"},
                    content=material_content,
                )
                assert material.status_code == 201, material.text
                material_id = material.json()["id"]
                download = await client.get(
                    f"/api/v1/special-performance-cases/{case_id}/materials/{material_id}/content",
                    headers=member_headers[0],
                )
                assert (
                    download.status_code == 200 and download.content == material_content
                )
                submitted = await client.post(
                    f"/api/v1/special-performance-cases/{case_id}/submit",
                    headers=member_headers[0],
                )
                assert submitted.status_code == 200, submitted.text
                assert submitted.json()["status"] == "submitted"
                submitted_at = _as_utc(submitted.json()["submitted_at"])
                due_at = _as_utc(submitted.json()["review_due_at"])
                assert abs((due_at - submitted_at).total_seconds() - 3 * 86400) < 2
                frozen = await client.patch(
                    f"/api/v1/special-performance-cases/{case_id}",
                    headers=member_headers[0],
                    json={"title": "must remain frozen"},
                )
                assert frozen.status_code == 409
                added_after_submit = await client.post(
                    f"/api/v1/special-performance-cases/{case_id}/materials/late",
                    params={"filename": "late.txt"},
                    headers={**member_headers[0], "Content-Type": "text/plain"},
                    content=b"late synthetic evidence",
                )
                assert added_after_submit.status_code == 409
                handled = await client.post(
                    f"/api/v1/special-performance-cases/{case_id}/handle",
                    headers=admin_headers,
                    json={"action": "start_review", "comment": "M8 acceptance"},
                )
                assert (
                    handled.status_code == 200
                    and handled.json()["status"] == "reviewing"
                )
                processed = await client.post(
                    f"/api/v1/special-performance-cases/{case_id}/review",
                    headers=admin_headers,
                    json={
                        "action": "approve",
                        "comment": "M8 acceptance approved",
                        "plugin_id": special_plugin_id,
                    },
                )
                assert processed.status_code == 200, processed.text
                assert processed.json()["status"] == "processed"
                assert processed.json()["plugin_execution_status"] == "success"
                assert processed.json()["achievement_id"]
                assert processed.json()["reviewed_by_user_id"] == admin_me.json()["id"]
                case_events = [
                    event["event_type"] for event in processed.json()["events"]
                ]
                assert "case_submitted" in case_events
                assert "case_approved" in case_events
                assert "case_processed" in case_events
                assert "notification_requested" in case_events
                special_eligible = await client.get(
                    "/api/v1/achievements/eligible", headers=member_headers[0]
                )
                assert any(
                    row["id"] == processed.json()["achievement_id"]
                    and row["source"] == "special_performance"
                    for row in special_eligible.json()["data"]
                )

                second_batch = await create_and_confirm_batch(
                    {teacher_ids[0]: 3600, teacher_ids[1]: 800}
                )
                second_results = {
                    result["teacher_id"]: result for result in second_batch["results"]
                }
                assert all(
                    second_results[teacher_id]["result_version"] == 2
                    for teacher_id in teacher_ids
                )
                admin_result_list = await client.get(
                    f"/api/v1/formal-calculation-results?period_id={marker}",
                    headers=admin_headers,
                )
                assert admin_result_list.status_code == 200
                result_rows = admin_result_list.json()["data"]
                assert len(result_rows) == 4
                for index, teacher_id in enumerate(teacher_ids):
                    own_results = await client.get(
                        f"/api/v1/me/formal-calculation-results?period_id={marker}",
                        headers=member_headers[index],
                    )
                    rows = own_results.json()["data"]
                    assert {row["result_version"] for row in rows} == {1, 2}
                    assert {row["teacher_id"] for row in rows} == {teacher_id}
                admin_export = await client.get(
                    f"/api/v1/formal-calculation-results/export?batch_id={second_batch['id']}",
                    headers=admin_headers,
                )
                assert admin_export.status_code == 200
                assert "text/csv" in admin_export.headers.get("content-type", "")
                audit = await client.get(
                    f"/api/v1/audit-events?resource_id={second_batch['id']}",
                    headers=admin_headers,
                )
                assert audit.status_code == 200 and audit.json()["data"]

                recovery_record_id = str(uuid.uuid4())
                attempt_id = str(uuid.uuid4())
                execution_id = str(uuid.uuid4())
                function_spec = {
                    "kind": "registered",
                    "name": "teaching_performance",
                    "version": "1.0.0",
                }
                async with async_session_factory() as session:
                    session.add(
                        CalculationRecord(
                            id=recovery_record_id,
                            table_name="m8_recovery_test",
                            period_id=marker,
                            input_data={"hours": 1, "rate": 1},
                            function_spec=function_spec,
                            requested_by_user_id=admin_me.json()["id"],
                            status="running",
                            attempt_count=1,
                            lock_version=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await session.flush()
                    session.add(
                        CalculationAttempt(
                            id=attempt_id,
                            record_id=recovery_record_id,
                            attempt_no=1,
                            execution_id=execution_id,
                            executor_type="registered",
                            status="running",
                            input_snapshot={"hours": 1, "rate": 1},
                            function_snapshot=function_spec,
                            started_at=now,
                        )
                    )
                    await session.commit()
                recovered = await client.post(
                    "/api/v1/runtime/recover-interrupted", headers=admin_headers
                )
                assert recovered.status_code == 200, recovered.text
                assert recovered.json()["recovered"] == 1
                assert recovered.json()["records"][0]["id"] == recovery_record_id
                recovered_record = await client.get(
                    f"/api/v1/records/{recovery_record_id}", headers=admin_headers
                )
                assert recovered_record.status_code == 200
                assert recovered_record.json()["status"] == "failed"
                assert (
                    recovered_record.json()["error"]["code"] == "EXECUTION_INTERRUPTED"
                )
                attempts = await client.get(
                    f"/api/v1/records/{recovery_record_id}/attempts",
                    headers=admin_headers,
                )
                assert attempts.status_code == 200
                assert attempts.json()["data"][0]["status"] == "failed"
        finally:
            try:
                await _cleanup_acceptance_data(
                    marker=marker,
                    teacher_ids=teacher_ids,
                    usernames=usernames,
                    plugin_keys=plugin_keys,
                    workflow_key=workflow_key,
                )
            finally:
                if previous_special is None:
                    _REGISTRY.pop(_SPECIAL_FUNCTION_KEY, None)
                else:
                    _REGISTRY[_SPECIAL_FUNCTION_KEY] = previous_special
        assert await _table_counts() == baseline

    asyncio.run(acceptance())
