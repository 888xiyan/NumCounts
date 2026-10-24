import asyncio
import os
from datetime import UTC, datetime

os.environ.setdefault(
    "DATABASE_URL", "mysql+asyncmy://numcounts_app:change-me@localhost:3306/numcounts"
)
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-thirty-two-bytes")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "admin-test-password")
os.environ.setdefault("SEED_USER_PASSWORD", "user-test-password")

from app.api.v1.monitoring import runtime_summary  # noqa: E402
from app.models.user import UserRole  # noqa: E402


class ResultRows:
    def all(self) -> list[tuple[str, int]]:
        return [("failed", 2), ("pending", 3), ("success", 5), ("running", 1)]


class MonitoringSession:
    def __init__(self) -> None:
        self.scalar_values = [
            datetime(2026, 10, 21, 8, tzinfo=UTC),
            datetime(2026, 10, 21, 9, tzinfo=UTC),
            12,
            1,
        ]

    async def execute(self, statement: object) -> ResultRows:
        return ResultRows()

    async def scalar(self, statement: object) -> int | datetime:
        return self.scalar_values.pop(0)


def test_runtime_summary_exposes_operational_counts_and_staleness_markers() -> None:
    async def request() -> None:
        response = await runtime_summary(MonitoringSession(), _=UserRole.ADMIN)  # type: ignore[arg-type]

        assert response.records_by_status == {
            "failed": 2,
            "pending": 3,
            "success": 5,
            "running": 1,
        }
        assert response.total_record_count == 11
        assert response.failed_record_count == 2
        assert response.oldest_pending_at == datetime(2026, 10, 21, 8, tzinfo=UTC)
        assert response.oldest_running_at == datetime(2026, 10, 21, 9, tzinfo=UTC)
        assert response.record_link_count == 12
        assert response.running_attempt_count == 1

    asyncio.run(request())
