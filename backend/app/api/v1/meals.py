from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_user
from app.core.responses import success_response
from app.models import User
from app.schemas.records import MealCreateRequest, MealPatchRequest
from app.services.meals import MealService, get_meal_service

router = APIRouter(prefix="/meals")


@router.get("")
def list_meals(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MealService, Depends(get_meal_service)],
    date: date | None = None,
) -> dict:
    data = service.list_meals(current_user.id, date)
    return success_response(data, request)


@router.post("")
def create_meal(
    payload: MealCreateRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MealService, Depends(get_meal_service)],
) -> dict:
    data = service.create_meal(current_user.id, payload)
    return success_response(data, request)


@router.get("/{meal_id}")
def get_meal(
    meal_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MealService, Depends(get_meal_service)],
) -> dict:
    data = service.get_meal(current_user.id, meal_id)
    return success_response(data, request)


@router.patch("/{meal_id}")
def update_meal(
    meal_id: str,
    payload: MealPatchRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MealService, Depends(get_meal_service)],
) -> dict:
    data = service.update_meal(current_user.id, meal_id, payload)
    return success_response(data, request)


@router.delete("/{meal_id}")
def delete_meal(
    meal_id: str,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MealService, Depends(get_meal_service)],
) -> dict:
    data = service.delete_meal(current_user.id, meal_id)
    return success_response(data, request)
