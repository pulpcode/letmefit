from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.services.dev_reset import DevResetService, get_dev_reset_service

router = APIRouter(prefix="/dev")


@router.post("/reset-current-user")
def reset_current_user(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DevResetService, Depends(get_dev_reset_service)],
) -> dict:
    data = service.reset_current_user(current_user.id)
    return success_response(data, request)
