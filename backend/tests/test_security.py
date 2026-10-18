import os

os.environ.setdefault(
    "DATABASE_URL", "mysql+asyncmy://numcounts_app:change-me@localhost:3306/numcounts"
)
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-thirty-two-bytes")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "admin-test-password")
os.environ.setdefault("SEED_USER_PASSWORD", "user-test-password")

import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import UserRole


def test_password_hash_is_verifiable() -> None:
    encoded = hash_password("correct-horse-battery-staple")

    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("not-the-password", encoded)


def test_access_token_contains_expected_identity() -> None:
    token = create_access_token(
        user_id="user-1", username="admin", role=UserRole.ADMIN
    )

    assert decode_access_token(token) == {
        "sub": "user-1",
        "username": "admin",
        "role": "ADMIN",
    }


def test_invalid_access_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid access token"):
        decode_access_token("not-a-jwt")
