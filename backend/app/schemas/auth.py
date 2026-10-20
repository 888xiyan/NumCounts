from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    id: str
    username: str
    role: Literal["USER", "ADMIN"]
    teacher_id: str | None
