from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RuntimeSummaryResponse(BaseModel):
    records_by_status: dict[str, int]
    oldest_pending_at: datetime | None
    record_link_count: int
    running_attempt_count: int


class RecoveryResponse(BaseModel):
    recovered: int
    records: list[dict[str, Any]]
