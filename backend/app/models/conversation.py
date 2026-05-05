from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, id_column, json_type, utc_datetime


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    dialogue_state_json: Mapped[Any | None] = mapped_column(json_type)
    dialogue_state_updated_at: Mapped[Any | None] = utc_datetime()


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = id_column()
    conversation_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversations.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content_json: Mapped[Any] = mapped_column(json_type, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64))
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Any] = utc_datetime(nullable=False)


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "file_id",
            name="uq_message_attachments_message_file",
        ),
    )

    id: Mapped[str] = id_column()
    message_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversation_messages.id"),
        nullable=False,
    )
    file_id: Mapped[str] = mapped_column(String(40), ForeignKey("upload_files.id"), nullable=False)
    created_at: Mapped[Any] = utc_datetime(nullable=False)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        Index("ix_conversation_summaries_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = id_column()
    conversation_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversations.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(40), ForeignKey("users.id"), nullable=False)
    from_message_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversation_messages.id"),
        nullable=False,
    )
    to_message_id: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("conversation_messages.id"),
        nullable=False,
    )
    summary_type: Mapped[str] = mapped_column(String(32), nullable=False, default="rolling")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="succeeded")
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[Any | None] = mapped_column(json_type)
    token_estimate: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[Any] = utc_datetime(nullable=False)
    updated_at: Mapped[Any | None] = utc_datetime()
