from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.profile import ProfileUpsertRequest
from app.services.profile import ProfileService, get_profile_service

router = APIRouter(prefix="/profile")


@router.get("")
def get_profile(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> dict:
    data = service.get_profile(current_user.id)
    return success_response(data, request)


@router.put("")
def upsert_profile(
    payload: ProfileUpsertRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> dict:
    data = service.upsert_profile(current_user.id, payload)
    return success_response(data, request)
