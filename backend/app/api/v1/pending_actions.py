from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.pending_action import PendingActionContinuationRequest, PendingActionUpdateRequest
from app.services.pending_actions import PendingActionService, get_pending_action_service

router = APIRouter(prefix="/agent/pending-actions")


@router.patch("/{pending_action_id}")
def update_pending_action(
    pending_action_id: str,
    payload: PendingActionUpdateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PendingActionService, Depends(get_pending_action_service)],
) -> dict:
    data = service.update_action(current_user.id, pending_action_id, payload)
    return success_response(data, request)


@router.post("/{pending_action_id}/confirm")
def confirm_pending_action(
    pending_action_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PendingActionService, Depends(get_pending_action_service)],
    payload: PendingActionContinuationRequest | None = None,
) -> dict:
    data = service.confirm_action(
        current_user.id,
        pending_action_id,
        payload or PendingActionContinuationRequest(),
    )
    return success_response(data, request)


@router.post("/{pending_action_id}/discard")
def discard_pending_action(
    pending_action_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[PendingActionService, Depends(get_pending_action_service)],
    payload: PendingActionContinuationRequest | None = None,
) -> dict:
    data = service.discard_action(
        current_user.id,
        pending_action_id,
        payload or PendingActionContinuationRequest(),
    )
    return success_response(data, request)
