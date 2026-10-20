import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, Index, String
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserRole(enum.StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uk_users_teacher_id", "teacher_id", unique=True),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    teacher_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
