from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import MealItem, MealRecord
from app.schemas.records import MealCreateRequest, MealItemWrite, MealPatchRequest
from app.services.time import local_date_from_utc, normalize_recorded_time

MEAL_FIELDS = (
    "source_type",
    "meal_type",
    "confidence",
    "source_pending_action_id",
    "notes",
)


class MealService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_meals(self, user_id: str, local_date: date | None = None) -> dict:
        query = select(MealRecord).where(
            MealRecord.user_id == user_id,
            MealRecord.deleted_at.is_(None),
        )
        if local_date:
            query = query.where(MealRecord.local_date == local_date)
        meals = list(self.db.scalars(query.order_by(MealRecord.recorded_at.desc())))
        return {"meals": [self._response(meal, self._items_by_meal_id(meal.id)) for meal in meals]}

    def get_meal(self, user_id: str, meal_id: str) -> dict:
        meal = self._get_owned_meal(user_id, meal_id)
        return self._response(meal, self._items_by_meal_id(meal.id))

    def create_meal(self, user_id: str, payload: MealCreateRequest, commit: bool = True) -> dict:
        recorded_at, local_date = normalize_recorded_time(payload.recorded_at, payload.recorded_tz)
        totals = self._totals(payload.items)
        meal = MealRecord(
            id=new_id("meal"),
            user_id=user_id,
            recorded_at=recorded_at,
            recorded_tz=payload.recorded_tz,
            local_date=local_date,
            source_type=payload.source_type,
            meal_type=payload.meal_type,
            total_calories=totals["calories"],
            total_protein_g=totals["protein_g"],
            total_carbs_g=totals["carbs_g"],
            total_fat_g=totals["fat_g"],
            confidence=payload.confidence,
            source_pending_action_id=payload.source_pending_action_id,
            notes=payload.notes,
        )
        self.db.add(meal)
        self.db.flush()
        self._add_items(meal.id, payload.items)
        self.db.flush()
        if commit:
            self.db.commit()
            return self.get_meal(user_id, meal.id)
        return self._response(meal, self._items_by_meal_id(meal.id))

    def update_meal(self, user_id: str, meal_id: str, payload: MealPatchRequest) -> dict:
        meal = self._get_owned_meal(user_id, meal_id)
        recorded_tz = payload.recorded_tz or meal.recorded_tz
        if payload.recorded_at is not None:
            meal.recorded_at, meal.local_date = normalize_recorded_time(
                payload.recorded_at,
                recorded_tz,
            )
            meal.recorded_tz = recorded_tz
        elif payload.recorded_tz is not None:
            meal.local_date = local_date_from_utc(meal.recorded_at, recorded_tz)
            meal.recorded_tz = recorded_tz

        for field in MEAL_FIELDS:
            if field in payload.model_fields_set:
                setattr(meal, field, getattr(payload, field))

        if payload.items is not None:
            totals = self._totals(payload.items)
            meal.total_calories = totals["calories"]
            meal.total_protein_g = totals["protein_g"]
            meal.total_carbs_g = totals["carbs_g"]
            meal.total_fat_g = totals["fat_g"]
            self.db.execute(delete(MealItem).where(MealItem.meal_record_id == meal.id))
            self._add_items(meal.id, payload.items)

        self.db.commit()
        return self.get_meal(user_id, meal.id)

    def delete_meal(self, user_id: str, meal_id: str) -> dict:
        meal = self._get_owned_meal(user_id, meal_id)
        meal.deleted_at = utc_now()
        self.db.commit()
        return {"success": True}

    def _get_owned_meal(self, user_id: str, meal_id: str) -> MealRecord:
        meal = self.db.scalar(
            select(MealRecord).where(
                MealRecord.id == meal_id,
                MealRecord.user_id == user_id,
                MealRecord.deleted_at.is_(None),
            )
        )
        if not meal:
            raise AppError("RESOURCE_NOT_FOUND", "餐食记录不存在", status_code=404)
        return meal

    def _add_items(self, meal_id: str, items: list[MealItemWrite]) -> None:
        for index, item in enumerate(items):
            self.db.add(
                MealItem(
                    id=new_id("mi"),
                    meal_record_id=meal_id,
                    display_order=index,
                    name=item.name,
                    alias=item.alias,
                    portion_text=item.portion_text,
                    portion_grams=item.portion_grams,
                    calories=item.calories,
                    protein_g=item.protein_g,
                    carbs_g=item.carbs_g,
                    fat_g=item.fat_g,
                    confidence=item.confidence,
                    user_corrected=item.user_corrected,
                )
            )

    def _items_by_meal_id(self, meal_id: str) -> list[MealItem]:
        return list(
            self.db.scalars(
                select(MealItem)
                .where(MealItem.meal_record_id == meal_id)
                .order_by(MealItem.display_order.asc(), MealItem.created_at.asc())
            )
        )

    def _totals(self, items: list[MealItemWrite]) -> dict[str, Decimal | None]:
        return {
            "calories": self._sum_optional(item.calories for item in items),
            "protein_g": self._sum_optional(item.protein_g for item in items),
            "carbs_g": self._sum_optional(item.carbs_g for item in items),
            "fat_g": self._sum_optional(item.fat_g for item in items),
        }

    def _sum_optional(self, values) -> Decimal | None:
        present = [value for value in values if value is not None]
        if not present:
            return None
        return sum(present, Decimal("0"))

    def _response(self, meal: MealRecord, items: list[MealItem]) -> dict:
        return {
            "id": meal.id,
            "recorded_at": meal.recorded_at,
            "recorded_tz": meal.recorded_tz,
            "local_date": meal.local_date,
            "source_type": meal.source_type,
            "meal_type": meal.meal_type,
            "total_calories": self._number(meal.total_calories),
            "total_protein_g": self._number(meal.total_protein_g),
            "total_carbs_g": self._number(meal.total_carbs_g),
            "total_fat_g": self._number(meal.total_fat_g),
            "confidence": self._number(meal.confidence),
            "source_pending_action_id": meal.source_pending_action_id,
            "notes": meal.notes,
            "items": [
                {
                    "id": item.id,
                    "name": item.name,
                    "alias": item.alias,
                    "portion_text": item.portion_text,
                    "portion_grams": self._number(item.portion_grams),
                    "calories": self._number(item.calories),
                    "protein_g": self._number(item.protein_g),
                    "carbs_g": self._number(item.carbs_g),
                    "fat_g": self._number(item.fat_g),
                    "confidence": self._number(item.confidence),
                    "user_corrected": item.user_corrected,
                }
                for item in items
            ],
        }

    def _number(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)


def get_meal_service(db: Annotated[Session, Depends(get_db)]) -> MealService:
    return MealService(db)
