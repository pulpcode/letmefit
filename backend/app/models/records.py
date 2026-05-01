from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, id_column, utc_datetime


class MealRecord(TimestampMixin, Base):
    __tablename__ = "meal_records"
    __table_args__ = (
        Index("ix_meal_records_user_date", "user_id", "local_date"),
        Index("ix_meal_records_user_recorded_at", "user_id", "recorded_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[Any] = utc_datetime(nullable=False)
    recorded_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    local_date: Mapped[Any] = mapped_column(mysql.DATE(), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    total_calories: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    total_protein_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    total_carbs_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    total_fat_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    source_pending_action_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("agent_pending_actions.id"),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[Any] = utc_datetime()


class MealItem(TimestampMixin, Base):
    __tablename__ = "meal_items"

    id: Mapped[str] = id_column()
    meal_record_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("meal_records.id"),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    alias: Mapped[str | None] = mapped_column(String(128))
    portion_text: Mapped[str | None] = mapped_column(String(128))
    portion_grams: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    calories: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    protein_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    carbs_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    fat_g: Mapped[Any] = mapped_column(mysql.DECIMAL(8, 2), nullable=True)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    user_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BodyMetricRecord(TimestampMixin, Base):
    __tablename__ = "body_metric_records"
    __table_args__ = (
        Index("ix_body_metrics_user_date", "user_id", "local_date"),
        Index("ix_body_metrics_user_recorded_at", "user_id", "recorded_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[Any] = utc_datetime(nullable=False)
    recorded_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    local_date: Mapped[Any] = mapped_column(mysql.DATE(), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    weight_kg: Mapped[Any] = mapped_column(mysql.DECIMAL(6, 2), nullable=True)
    body_fat_percentage: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 2), nullable=True)
    bmi: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 2), nullable=True)
    muscle_mass_kg: Mapped[Any] = mapped_column(mysql.DECIMAL(6, 2), nullable=True)
    water_percentage: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 2), nullable=True)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    source_pending_action_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("agent_pending_actions.id"),
    )
    deleted_at: Mapped[Any] = utc_datetime()
