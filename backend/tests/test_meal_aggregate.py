from datetime import date, datetime
from decimal import Decimal

from app.models import MealRecord
from app.services.meals import MealService


class FakeScalars:
    def __init__(self, items: list[MealRecord]) -> None:
        self.items = items

    def __iter__(self):
        return iter(self.items)


class FakeDb:
    def __init__(self, items: list[MealRecord]) -> None:
        self.items = items

    def scalars(self, query):
        return FakeScalars(self.items)


def _meal(
    calories: float | None = 600,
    protein: float | None = 40,
    carbs: float | None = 70,
    fat: float | None = 20,
    local_date_value: date = date(2026, 5, 9),
) -> MealRecord:
    return MealRecord(
        id="meal_test",
        user_id="user_test",
        recorded_at=datetime(2026, 5, 9, 12, 0, 0),
        recorded_tz="Asia/Shanghai",
        local_date=local_date_value,
        source_type="manual",
        meal_type="lunch",
        total_calories=Decimal(str(calories)) if calories is not None else None,
        total_protein_g=Decimal(str(protein)) if protein is not None else None,
        total_carbs_g=Decimal(str(carbs)) if carbs is not None else None,
        total_fat_g=Decimal(str(fat)) if fat is not None else None,
    )


def test_aggregate_daily_returns_zeros_when_no_meals() -> None:
    service = MealService(db=FakeDb([]))

    result = service.aggregate_daily("user_test", date(2026, 5, 9))

    assert result["date"] == "2026-05-09"
    assert result["meal_count"] == 0
    assert result["consumed"] == {
        "calories": None,
        "protein_g": None,
        "carbs_g": None,
        "fat_g": None,
    }
    assert result["target"] is None
    assert result["completion_percent"] is None
    assert result["remaining"] is None


def test_aggregate_daily_sums_multiple_meals_with_target() -> None:
    service = MealService(
        db=FakeDb(
            [
                _meal(calories=420, protein=25, carbs=50, fat=15),
                _meal(calories=680, protein=45, carbs=70, fat=25),
            ]
        ),
    )

    result = service.aggregate_daily(
        "user_test",
        date(2026, 5, 9),
        target={"calories": 2000, "protein_g": 120, "carbs_g": 200, "fat_g": 60},
    )

    assert result["meal_count"] == 2
    assert result["consumed"] == {
        "calories": 1100.0,
        "protein_g": 70.0,
        "carbs_g": 120.0,
        "fat_g": 40.0,
    }
    assert result["completion_percent"] == {
        "calories": 55,
        "protein_g": 58,
        "carbs_g": 60,
        "fat_g": 67,
    }
    assert result["remaining"] == {
        "calories": 900.0,
        "protein_g": 50.0,
        "carbs_g": 80.0,
        "fat_g": 20.0,
    }


def test_aggregate_daily_skips_none_totals() -> None:
    service = MealService(
        db=FakeDb(
            [
                _meal(calories=300, protein=None, carbs=40, fat=10),
                _meal(calories=None, protein=20, carbs=None, fat=None),
            ]
        ),
    )

    result = service.aggregate_daily("user_test", date(2026, 5, 9))

    assert result["consumed"]["calories"] == 300.0
    assert result["consumed"]["protein_g"] == 20.0
    assert result["consumed"]["carbs_g"] == 40.0
    assert result["consumed"]["fat_g"] == 10.0


def test_aggregate_daily_remaining_can_be_negative_when_over_target() -> None:
    service = MealService(db=FakeDb([_meal(calories=2300, protein=130, carbs=250, fat=80)]))

    result = service.aggregate_daily(
        "user_test",
        date(2026, 5, 9),
        target={"calories": 2000, "protein_g": 120, "carbs_g": 200, "fat_g": 60},
    )

    assert result["remaining"]["calories"] == -300.0
    assert result["remaining"]["fat_g"] == -20.0
    assert result["completion_percent"]["calories"] == 115
