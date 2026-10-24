from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RuntimeSummaryResponse(BaseModel):
    records_by_status: dict[str, int]
    total_record_count: int
    failed_record_count: int
    oldest_pending_at: datetime | None
    oldest_running_at: datetime | None
    record_link_count: int
    running_attempt_count: int


class RecoveryResponse(BaseModel):
    recovered: int
    records: list[dict[str, Any]]
