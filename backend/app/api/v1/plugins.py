from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.errors import APIError
from app.db.session import get_session
from app.models.plugin import RulePlugin, RulePluginStatus
from app.models.user import User, UserRole
from app.schemas.plugins import (
    CreateRulePluginRequest,
    RulePluginListResponse,
    RulePluginResponse,
)
from app.services.plugin_service import (
    create_rule_plugin,
    get_rule_plugin,
    list_rule_plugins,
    set_rule_plugin_status,
)

router = APIRouter(prefix="/rule-plugins", tags=["rule-plugins"])


def _plugin_response(plugin: RulePlugin) -> RulePluginResponse:
    return RulePluginResponse(
        id=plugin.id,
        plugin_key=plugin.plugin_key,
        version=plugin.version,
        name=plugin.name,
        description=plugin.description,
        function=plugin.function_spec,
        input_defaults=plugin.input_defaults,
        purpose=plugin.purpose,
        status=plugin.status,
        created_at=plugin.created_at,
        updated_at=plugin.updated_at,
    )


@router.post("", response_model=RulePluginResponse, status_code=status.HTTP_201_CREATED)
async def create_plugin(
    request: CreateRulePluginRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RulePluginResponse:
    return _plugin_response(await create_rule_plugin(session, request=request))


@router.get("", response_model=RulePluginListResponse)
async def list_plugins(
    status_filter: RulePluginStatus | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> RulePluginListResponse:
    if user.role == UserRole.USER:
        status_filter = RulePluginStatus.ENABLED
    plugins = await list_rule_plugins(session, status=status_filter)
    return RulePluginListResponse(data=[_plugin_response(plugin) for plugin in plugins])


@router.get("/{plugin_id}", response_model=RulePluginResponse)
async def get_plugin(
    plugin_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.USER)),
) -> RulePluginResponse:
    plugin = await get_rule_plugin(session, plugin_id=plugin_id)
    if user.role == UserRole.USER and plugin.status != RulePluginStatus.ENABLED:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="RULE_PLUGIN_NOT_AVAILABLE",
            message="rule plugin is not available to members",
        )
    return _plugin_response(plugin)


@router.post("/{plugin_id}/enable", response_model=RulePluginResponse)
async def enable_plugin(
    plugin_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RulePluginResponse:
    return _plugin_response(
        await set_rule_plugin_status(session, plugin_id=plugin_id, enabled=True)
    )


@router.post("/{plugin_id}/disable", response_model=RulePluginResponse)
async def disable_plugin(
    plugin_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> RulePluginResponse:
    return _plugin_response(
        await set_rule_plugin_status(session, plugin_id=plugin_id, enabled=False)
    )
