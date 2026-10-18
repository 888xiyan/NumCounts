from typing import Any

from fastapi import HTTPException


class APIError(HTTPException):
    """HTTP error with the stable error envelope used by the public API."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        detail: dict[str, Any] = {
            "code": code,
            "message": message,
            "retryable": retryable,
        }
        if details:
            detail["details"] = details
        super().__init__(status_code=status_code, detail=detail, headers=headers)
