import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RecordLinkType(enum.StrEnum):
    DATA = "data"
    EXECUTION = "execution"


class RecordLink(Base):
    __tablename__ = "record_links"
    __table_args__ = (
        UniqueConstraint("source_record_id", "input_key", name="uk_record_link_input"),
        Index("idx_record_links_target", "target_record_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calculation_records.id"), nullable=False
    )
    target_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calculation_records.id"), nullable=False
    )
    link_type: Mapped[RecordLinkType] = mapped_column(String(16), nullable=False)
    input_key: Mapped[str] = mapped_column(String(64), nullable=False)
    target_path: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
