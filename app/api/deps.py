from collections.abc import Callable

from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token_data = decode_access_token(credentials.credentials)
    except ValueError as error:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_ACCESS_TOKEN",
            message="invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    user = await session.get(User, token_data["sub"])
    if user is None or not user.is_active:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="USER_UNAVAILABLE",
            message="user is unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: UserRole) -> Callable[..., User]:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="INSUFFICIENT_PERMISSIONS",
                message="insufficient permissions",
            )
        return user

    return dependency
