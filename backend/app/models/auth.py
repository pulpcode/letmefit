from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import HASH_LENGTH, STATUS_LENGTH, TimestampMixin, id_column, utc_datetime


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_status", "status"),)

    id: Mapped[str] = id_column()
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="86")
    phone_verified_at: Mapped[Any] = utc_datetime()
    status: Mapped[str] = mapped_column(String(STATUS_LENGTH), nullable=False, default="active")
    last_login_at: Mapped[Any] = utc_datetime()


class RefreshSession(TimestampMixin, Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index("ix_refresh_sessions_user_id", "user_id"),
        Index("ix_refresh_sessions_expires_at", "expires_at"),
        Index("ix_refresh_sessions_revoked_at", "revoked_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(
        String(HASH_LENGTH),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[Any] = utc_datetime(nullable=False)
    revoked_at: Mapped[Any] = utc_datetime()
    created_ip_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class SmsVerificationEvent(Base):
    __tablename__ = "sms_verification_events"
    __table_args__ = (
        Index("ix_sms_events_phone_created", "phone_number_hash", "created_at"),
        Index("ix_sms_events_created_at", "created_at"),
    )

    id: Mapped[str] = id_column()
    phone_number_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False, default="86")
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_code: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(HASH_LENGTH))
    created_at: Mapped[Any] = utc_datetime(nullable=False)


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user_id"),)

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    age: Mapped[int | None] = mapped_column(SmallInteger)
    sex: Mapped[str | None] = mapped_column(String(32))
    height_cm: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 2), nullable=True)
    current_weight_kg: Mapped[Any] = mapped_column(mysql.DECIMAL(6, 2), nullable=True)
    target_weight_kg: Mapped[Any] = mapped_column(mysql.DECIMAL(6, 2), nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(32))
    goal_type: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[Any] = utc_datetime()
