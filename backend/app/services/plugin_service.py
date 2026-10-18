"""Versioned rule-plugin management.

Plugins deliberately contain no source code.  They freeze a trusted function
reference plus operator-friendly default inputs, then the calculation core
executes the resolved function under its normal record lifecycle.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.executors import get_executor
from app.functions import FunctionExecutionError, get_registered_function
from app.models.plugin import RulePlugin, RulePluginStatus
from app.schemas.plugins import CreateRulePluginRequest
from app.schemas.records import ExternalFunctionSpec, RegisteredFunctionSpec


def _now() -> datetime:
    return datetime.now(UTC)


def plugin_snapshot(plugin: RulePlugin) -> dict[str, Any]:
    """Return the immutable details copied into records and workflow nodes."""
    return {
        "id": plugin.id,
        "plugin_key": plugin.plugin_key,
        "version": plugin.version,
        "name": plugin.name,
        "description": plugin.description,
        "function": plugin.function_spec,
        "input_defaults": plugin.input_defaults,
    }


def _validate_function_reference(request: CreateRulePluginRequest) -> None:
    try:
        if isinstance(request.function, RegisteredFunctionSpec):
            get_registered_function(request.function.name, request.function.version)
        elif isinstance(request.function, ExternalFunctionSpec):
            get_executor(request.function.executor_id)
        else:  # Defensive guard for future function kinds.
            raise FunctionExecutionError(
                "INVALID_PLUGIN_FUNCTION",
                "plugins can only reference a registered or external function",
            )
    except FunctionExecutionError as error:
        raise APIError(
            status_code=(
                404
                if error.code in {"FUNCTION_NOT_FOUND", "EXECUTOR_NOT_FOUND"}
                else 422
            ),
            code=error.code,
            message=error.message,
            details=error.details,
        ) from error


async def create_rule_plugin(
    session: AsyncSession, *, request: CreateRulePluginRequest
) -> RulePlugin:
    _validate_function_reference(request)
    now = _now()
    plugin = RulePlugin(
        plugin_key=request.plugin_key,
        version=request.version,
        name=request.name,
        description=request.description,
        function_spec=request.function.model_dump(),
        input_defaults=request.input_defaults,
        status=RulePluginStatus.DISABLED,
        created_at=now,
        updated_at=now,
    )
    session.add(plugin)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise APIError(
            status_code=409,
            code="RULE_PLUGIN_VERSION_EXISTS",
            message="a plugin with the same key and version already exists",
            details={"plugin_key": request.plugin_key, "version": request.version},
        ) from error
    await session.refresh(plugin)
    return plugin


async def get_rule_plugin(session: AsyncSession, *, plugin_id: str) -> RulePlugin:
    plugin = await session.get(RulePlugin, plugin_id)
    if plugin is None:
        raise APIError(
            status_code=404,
            code="RULE_PLUGIN_NOT_FOUND",
            message="rule plugin was not found",
        )
    return plugin


async def list_rule_plugins(
    session: AsyncSession, *, status: RulePluginStatus | None = None
) -> list[RulePlugin]:
    statement = select(RulePlugin)
    if status is not None:
        statement = statement.where(RulePlugin.status == status)
    statement = statement.order_by(RulePlugin.plugin_key, RulePlugin.version)
    return list((await session.scalars(statement)).all())


async def set_rule_plugin_status(
    session: AsyncSession, *, plugin_id: str, enabled: bool
) -> RulePlugin:
    plugin = await get_rule_plugin(session, plugin_id=plugin_id)
    plugin.status = (
        RulePluginStatus.ENABLED if enabled else RulePluginStatus.DISABLED
    )
    plugin.updated_at = _now()
    await session.commit()
    await session.refresh(plugin)
    return plugin


async def resolve_enabled_plugin_snapshot(
    session: AsyncSession, *, plugin_id: str
) -> dict[str, Any]:
    plugin = await get_rule_plugin(session, plugin_id=plugin_id)
    if plugin.status != RulePluginStatus.ENABLED:
        raise APIError(
            status_code=409,
            code="RULE_PLUGIN_DISABLED",
            message="disabled rule plugins cannot be used for new records",
            details={"plugin_id": plugin_id},
        )
    return plugin_snapshot(plugin)
