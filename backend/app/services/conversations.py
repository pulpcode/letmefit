from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.mock_extraction import MockExtractionService
from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import Conversation, ConversationMessage, MessageAttachment, UploadFile
from app.schemas.conversation import (
    ConversationCreateRequest,
    MessageContentItem,
    MessageCreateRequest,
)


class ConversationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.extraction_service = MockExtractionService(db)

    def create_conversation(self, user_id: str, payload: ConversationCreateRequest) -> dict:
        conversation = Conversation(
            id=new_id("conv"),
            user_id=user_id,
            title=payload.title,
            status="active",
        )
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return {
            "conversation_id": conversation.id,
            "conversation": self._conversation_response(conversation),
        }

    def list_conversations(self, user_id: str) -> dict:
        conversations = list(
            self.db.scalars(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
            )
        )
        return {"conversations": [self._conversation_response(item) for item in conversations]}

    def list_messages(self, user_id: str, conversation_id: str) -> dict:
        self._get_owned_conversation(user_id, conversation_id)
        messages = list(
            self.db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.created_at.asc())
            )
        )
        return {"messages": [self._message_response(message) for message in messages]}

    def send_message(
        self,
        user_id: str,
        conversation_id: str,
        payload: MessageCreateRequest,
    ) -> dict:
        conversation = self._get_owned_conversation(user_id, conversation_id)
        content = [item.model_dump(mode="json", exclude_none=True) for item in payload.content]
        user_message = ConversationMessage(
            id=new_id("msg"),
            conversation_id=conversation.id,
            user_id=user_id,
            role="user",
            content_json=content,
            intent=None,
            requires_review=False,
            created_at=utc_now(),
        )
        self.db.add(user_message)
        self.db.flush()
        self._add_message_attachments(user_id, user_message.id, payload.content)

        extraction_result = self.extraction_service.process_message(
            user_id=user_id,
            conversation_id=conversation.id,
            message_id=user_message.id,
            content=payload.content,
        )
        assistant_message = ConversationMessage(
            id=new_id("msg"),
            conversation_id=conversation.id,
            user_id=user_id,
            role="assistant",
            content_json=[{"type": "text", "text": extraction_result["assistant_text"]}],
            intent=extraction_result["intent"],
            requires_review=extraction_result["requires_review"],
            created_at=utc_now(),
        )
        user_message.intent = extraction_result["intent"]
        user_message.requires_review = extraction_result["requires_review"]
        conversation.status = "active"
        self.db.add(assistant_message)
        self.db.commit()

        return {
            "message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "assistant_text": extraction_result["assistant_text"],
            "intent": extraction_result["intent"],
            "requires_review": extraction_result["requires_review"],
            "pending_actions": extraction_result["pending_actions"],
        }

    def _add_message_attachments(
        self,
        user_id: str,
        message_id: str,
        content: list[MessageContentItem],
    ) -> None:
        file_ids = self._extract_file_ids(content)
        if not file_ids:
            return

        files = list(
            self.db.scalars(
                select(UploadFile).where(
                    UploadFile.id.in_(file_ids),
                    UploadFile.user_id == user_id,
                    UploadFile.deleted_at.is_(None),
                    UploadFile.status != "deleted",
                )
            )
        )
        found_ids = {file.id for file in files}
        missing_ids = sorted(set(file_ids) - found_ids)
        if missing_ids:
            raise AppError(
                "RESOURCE_NOT_FOUND",
                "消息引用的文件不存在",
                status_code=404,
                details={"file_ids": missing_ids},
            )

        for file_id in sorted(set(file_ids)):
            self.db.add(
                MessageAttachment(
                    id=new_id("ma"),
                    message_id=message_id,
                    file_id=file_id,
                    created_at=utc_now(),
                )
            )

    def _extract_file_ids(self, content: list[MessageContentItem]) -> list[str]:
        file_ids = []
        for item in content:
            if item.type == "text":
                if not item.text:
                    raise AppError("VALIDATION_ERROR", "文本消息不能为空", status_code=422)
                continue
            if not item.file_id:
                raise AppError("VALIDATION_ERROR", "媒体消息必须包含 file_id", status_code=422)
            file_ids.append(item.file_id)
        return file_ids

    def _get_owned_conversation(self, user_id: str, conversation_id: str) -> Conversation:
        conversation = self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if not conversation:
            raise AppError("RESOURCE_NOT_FOUND", "会话不存在", status_code=404)
        return conversation

    def _conversation_response(self, conversation: Conversation) -> dict:
        return {
            "id": conversation.id,
            "title": conversation.title,
            "status": conversation.status,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
        }

    def _message_response(self, message: ConversationMessage) -> dict:
        return {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content_json,
            "intent": message.intent,
            "requires_review": message.requires_review,
            "created_at": message.created_at,
        }


def get_conversation_service(
    db: Annotated[Session, Depends(get_db)],
) -> ConversationService:
    return ConversationService(db)
