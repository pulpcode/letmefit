from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, id_column, json_type, utc_datetime


class AgentExtraction(Base):
    __tablename__ = "agent_extractions"
    __table_args__ = (
        Index("ix_agent_extractions_user_created", "user_id", "created_at"),
        Index("ix_agent_extractions_message", "message_id"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("conversations.id"),
    )
    message_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("conversation_messages.id"),
    )
    input_types_json: Mapped[Any] = mapped_column(json_type, nullable=False)
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    raw_output_json: Mapped[Any] = mapped_column(json_type, nullable=True)
    warnings_json: Mapped[Any] = mapped_column(json_type, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[Any] = utc_datetime(nullable=False)


class AgentPendingAction(TimestampMixin, Base):
    __tablename__ = "agent_pending_actions"
    __table_args__ = (
        Index("ix_pending_actions_user_status", "user_id", "status"),
        Index("ix_pending_actions_conversation_status", "conversation_id", "status"),
        Index("ix_pending_actions_expires_at", "expires_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversations.id"),
        nullable=False,
    )
    source_message_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversation_messages.id"),
        nullable=False,
    )
    extraction_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("agent_extractions.id"),
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    draft_payload_json: Mapped[Any] = mapped_column(json_type, nullable=False)
    warnings_json: Mapped[Any] = mapped_column(json_type, nullable=True)
    confidence: Mapped[Any] = mapped_column(mysql.DECIMAL(5, 4), nullable=True)
    confirmed_at: Mapped[Any] = utc_datetime()
    committed_record_type: Mapped[str | None] = mapped_column(String(32))
    committed_record_id: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[Any] = utc_datetime()
