"""Trusted external-executor configuration and invocation helpers."""

from app.executors.client import execute_external_function
from app.executors.registry import ExternalExecutorNotFoundError, get_executor

__all__ = [
    "ExternalExecutorNotFoundError",
    "execute_external_function",
    "get_executor",
]
