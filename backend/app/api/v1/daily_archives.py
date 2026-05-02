from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.services.archives import DailyArchiveService, get_daily_archive_service

router = APIRouter(prefix="/daily-archives")


@router.get("/{archive_date}")
def get_daily_archive(
    archive_date: date,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DailyArchiveService, Depends(get_daily_archive_service)],
) -> dict:
    data = service.get_archive(current_user.id, archive_date)
    return success_response(data, request)
