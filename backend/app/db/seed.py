import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models.user import User, UserRole


async def upsert_seed_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: UserRole,
    teacher_id: str | None = None,
) -> None:
    user = await session.scalar(select(User).where(User.username == username))
    now = datetime.now(UTC)
    if user is None:
        session.add(
            User(
                username=username,
                teacher_id=teacher_id,
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        return

    user.role = role
    user.teacher_id = teacher_id
    user.is_active = True
    user.updated_at = now


async def seed() -> None:
    async with async_session_factory() as session:
        await upsert_seed_user(
            session,
            username=settings.seed_admin_username,
            password=settings.seed_admin_password,
            role=UserRole.ADMIN,
        )
        await upsert_seed_user(
            session,
            username=settings.seed_user_username,
            password=settings.seed_user_password,
            role=UserRole.USER,
            teacher_id=settings.seed_user_teacher_id or settings.seed_user_username,
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
