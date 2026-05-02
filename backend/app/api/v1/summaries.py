from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.archive import SummaryGenerateRequest
from app.services.archives import DailySummaryService, get_daily_summary_service

router = APIRouter(prefix="/summaries")


@router.post("/generate")
def generate_summary(
    payload: SummaryGenerateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DailySummaryService, Depends(get_daily_summary_service)],
) -> dict:
    data = service.generate_summary(current_user.id, payload.date, payload.timezone)
    return success_response(data, request)
