import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RulePluginStatus(enum.StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class RulePluginPurpose(enum.StrEnum):
    GENERAL = "general"
    SPECIAL_CASE = "special_case"


class RulePlugin(Base):
    """An immutable, versioned shortcut to an approved executable function."""

    __tablename__ = "rule_plugins"
    __table_args__ = (
        UniqueConstraint("plugin_key", "version", name="uk_rule_plugin_key_version"),
        Index("idx_rule_plugins_status", "status"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    plugin_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    function_spec: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    purpose: Mapped[RulePluginPurpose] = mapped_column(
        String(24), nullable=False, default=RulePluginPurpose.GENERAL
    )
    status: Mapped[RulePluginStatus] = mapped_column(
        String(16), nullable=False, default=RulePluginStatus.DISABLED
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
