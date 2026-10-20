from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.errors import APIError
from app.core.security import create_access_token
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse
from app.services.auth_service import authenticate_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    user = await authenticate_user(
        session, username=request.username, password=request.password
    )
    if user is None:
        raise APIError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="INVALID_CREDENTIALS",
            message="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(
            user_id=user.id, username=user.username, role=user.role
        ),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=user.id,
        username=user.username,
        role=user.role.value,
        teacher_id=user.teacher_id,
    )
