from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.records import BodyMetricCreateRequest, BodyMetricPatchRequest
from app.services.body_metrics import BodyMetricService, get_body_metric_service

router = APIRouter(prefix="/body-metrics")


@router.get("")
def list_body_metrics(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BodyMetricService, Depends(get_body_metric_service)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    data = service.list_body_metrics(current_user.id, date_from, date_to)
    return success_response(data, request)


@router.post("")
def create_body_metric(
    payload: BodyMetricCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BodyMetricService, Depends(get_body_metric_service)],
) -> dict:
    data = service.create_body_metric(current_user.id, payload)
    return success_response(data, request)


@router.get("/{body_metric_id}")
def get_body_metric(
    body_metric_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BodyMetricService, Depends(get_body_metric_service)],
) -> dict:
    data = service.get_body_metric(current_user.id, body_metric_id)
    return success_response(data, request)


@router.patch("/{body_metric_id}")
def update_body_metric(
    body_metric_id: str,
    payload: BodyMetricPatchRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BodyMetricService, Depends(get_body_metric_service)],
) -> dict:
    data = service.update_body_metric(current_user.id, body_metric_id, payload)
    return success_response(data, request)


@router.delete("/{body_metric_id}")
def delete_body_metric(
    body_metric_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BodyMetricService, Depends(get_body_metric_service)],
) -> dict:
    data = service.delete_body_metric(current_user.id, body_metric_id)
    return success_response(data, request)
