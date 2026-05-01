from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import id_column, utc_datetime


class UploadFile(Base):
    __tablename__ = "upload_files"
    __table_args__ = (
        Index("ix_upload_files_user_created", "user_id", "created_at"),
        Index("ix_upload_files_status", "status"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    client_local_ref: Mapped[str | None] = mapped_column(String(256))
    bucket: Mapped[str | None] = mapped_column(String(128))
    object_key: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[Any] = utc_datetime(nullable=False)
    deleted_at: Mapped[Any] = utc_datetime()
