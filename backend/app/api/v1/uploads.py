from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.upload import UploadCreateRequest
from app.services.uploads import UploadService, get_upload_service

router = APIRouter(prefix="/uploads")


@router.post("")
def create_upload(
    payload: UploadCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> dict:
    data = service.create_upload(current_user.id, payload)
    return success_response(data, request)


@router.get("/{file_id}")
def get_upload(
    file_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> dict:
    data = service.get_upload(current_user.id, file_id)
    return success_response(data, request)


@router.delete("/{file_id}")
def delete_upload(
    file_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UploadService, Depends(get_upload_service)],
) -> dict:
    data = service.delete_upload(current_user.id, file_id)
    return success_response(data, request)
