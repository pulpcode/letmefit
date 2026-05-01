from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.service import AuthService, get_auth_service
from app.core.responses import success_response
from app.schemas.auth import LogoutRequest, RefreshRequest, SmsSendRequest, SmsVerifyRequest

router = APIRouter(prefix="/auth")


@router.post("/sms/send")
def send_sms(
    payload: SmsSendRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    data = service.send_sms(payload.phone_number, payload.purpose, request)
    return success_response(data, request)


@router.post("/sms/verify")
def verify_sms(
    payload: SmsVerifyRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    data = service.verify_sms(payload.phone_number, payload.code, request)
    return success_response(data, request)


@router.post("/refresh")
def refresh_token(
    payload: RefreshRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    data = service.refresh_access_token(payload.refresh_token)
    return success_response(data, request)


@router.post("/logout")
def logout(
    payload: LogoutRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict:
    data = service.logout(payload.refresh_token)
    return success_response(data, request)
