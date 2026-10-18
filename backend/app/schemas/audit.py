from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: str
    actor_user_id: str | None
    event_type: str
    resource_type: str
    resource_id: str
    details: dict[str, Any]
    created_at: datetime


class AuditEventListResponse(BaseModel):
    data: list[AuditEventResponse]
