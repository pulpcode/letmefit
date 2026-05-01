from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, id_column, json_type, utc_datetime


class DailyArchive(TimestampMixin, Base):
    __tablename__ = "daily_archives"
    __table_args__ = (
        UniqueConstraint("user_id", "archive_date", name="uq_daily_archives_user_date"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    archive_date: Mapped[Any] = mapped_column(mysql.DATE(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    meal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_metric_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calorie_total: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    protein_total_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    carbs_total_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    fat_total_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    completeness_score: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    last_calculated_at: Mapped[Any] = utc_datetime(nullable=False)


class DailySummary(TimestampMixin, Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "summary_date", name="uq_daily_summaries_user_date"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    archive_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("daily_archives.id"))
    summary_date: Mapped[Any] = mapped_column(mysql.DATE(), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggestions_json: Mapped[Any] = mapped_column(json_type, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    generation_status: Mapped[str] = mapped_column(String(32), nullable=False)


class UserMemory(TimestampMixin, Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        Index("ix_user_memories_user_type_key", "user_id", "memory_type", "memory_key"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_key: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_value_json: Mapped[Any] = mapped_column(json_type, nullable=False)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen_at: Mapped[Any] = utc_datetime(nullable=False)
