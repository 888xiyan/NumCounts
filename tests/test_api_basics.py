import asyncio
import os

import httpx

os.environ.setdefault(
    "DATABASE_URL", "mysql+asyncmy://numcounts_app:change-me@localhost:3306/numcounts"
)
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-thirty-two-bytes")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "admin-test-password")
os.environ.setdefault("SEED_USER_PASSWORD", "user-test-password")

from app.db.session import get_session
from app.main import app


class EmptySession:
    async def scalar(self, statement: object) -> None:
        return None


async def empty_session_override() -> EmptySession:
    yield EmptySession()


def test_live_health_includes_request_id() -> None:
    async def request() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/health/live", headers={"X-Request-Id": "health-test"}
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Request-Id"] == "health-test"

    asyncio.run(request())


def test_invalid_login_uses_standard_error_envelope() -> None:
    app.dependency_overrides[get_session] = empty_session_override

    async def request() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                headers={"X-Request-Id": "login-test"},
                json={"username": "missing", "password": "incorrect"},
            )

        assert response.status_code == 401
        assert response.headers["X-Request-Id"] == "login-test"
        assert response.json() == {
            "error": {
                "code": "INVALID_CREDENTIALS",
                "message": "invalid username or password",
                "retryable": False,
            },
            "request_id": "login-test",
        }

    try:
        asyncio.run(request())
    finally:
        app.dependency_overrides.clear()
