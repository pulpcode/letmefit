from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageContentItem(BaseModel):
    type: Literal["text", "image", "audio"]
    text: str | None = Field(default=None, max_length=4000)
    file_id: str | None = Field(default=None, max_length=40)
    source: str | None = Field(default=None, max_length=32)
    duration_seconds: int | None = Field(default=None, ge=0, le=3600)


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=128)


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class MessageCreateRequest(BaseModel):
    content: list[MessageContentItem] = Field(min_length=1, max_length=20)
    include_debug_context: bool = False


class ConversationMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: list[dict]
    intent: str | None
    requires_review: bool
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[ConversationMessageResponse]


class MessageSendResponse(BaseModel):
    message_id: str
    assistant_message_id: str
    assistant_text: str
    intent: str
    requires_review: bool
    pending_actions: list[dict]
    committed_records: list[dict] = Field(default_factory=list)
    debug_context: dict[str, Any] | None = None
