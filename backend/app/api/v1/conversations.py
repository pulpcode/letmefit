import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.conversation import ConversationCreateRequest, MessageCreateRequest
from app.services.conversations import ConversationService, get_conversation_service
from app.services.pending_actions import PendingActionService, get_pending_action_service

router = APIRouter(prefix="/conversations")


@router.post("")
def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict:
    data = service.create_conversation(current_user.id, payload)
    return success_response(data, request)


@router.get("")
def list_conversations(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict:
    data = service.list_conversations(current_user.id)
    return success_response(data, request)


@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    payload: MessageCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict:
    data = service.send_message(current_user.id, conversation_id, payload)
    return success_response(data, request)


def _sse(event: str, data: dict) -> str:
    def _default(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=_default)}\n\n"


@router.post("/{conversation_id}/messages/stream")
def send_message_stream(
    conversation_id: str,
    payload: MessageCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
):
    def generate():
        try:
            for event, data in service.send_message_stream_events(
                current_user.id,
                conversation_id,
                payload,
            ):
                yield _sse(event, data)
        except Exception as exc:
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict:
    data = service.list_messages(current_user.id, conversation_id)
    return success_response(data, request)


@router.get("/{conversation_id}/pending-actions")
def list_pending_actions(
    conversation_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PendingActionService, Depends(get_pending_action_service)],
) -> dict:
    data = service.list_for_conversation(current_user.id, conversation_id)
    return success_response(data, request)
