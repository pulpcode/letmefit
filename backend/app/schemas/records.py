from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

MealSourceType = Literal["photo", "voice", "text", "manual", "mixed"]
MealType = Literal["breakfast", "lunch", "dinner", "snack", "unknown"]
BodyMetricSourceType = Literal["scale_photo", "voice", "text", "manual"]


class MealItemWrite(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    alias: str | None = Field(default=None, max_length=128)
    portion_text: str | None = Field(default=None, max_length=128)
    portion_grams: Decimal | None = Field(default=None, ge=0, le=10000)
    calories: Decimal | None = Field(default=None, ge=0, le=20000)
    protein_g: Decimal | None = Field(default=None, ge=0, le=2000)
    carbs_g: Decimal | None = Field(default=None, ge=0, le=2000)
    fat_g: Decimal | None = Field(default=None, ge=0, le=2000)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    user_corrected: bool = False


class MealCreateRequest(BaseModel):
    recorded_at: datetime
    recorded_tz: str = Field(default="Asia/Shanghai", max_length=64)
    source_type: MealSourceType
    meal_type: MealType
    items: list[MealItemWrite] = Field(min_length=1, max_length=50)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_pending_action_id: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class MealPatchRequest(BaseModel):
    recorded_at: datetime | None = None
    recorded_tz: str | None = Field(default=None, max_length=64)
    source_type: MealSourceType | None = None
    meal_type: MealType | None = None
    items: list[MealItemWrite] | None = Field(default=None, min_length=1, max_length=50)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_pending_action_id: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)


class MealItemResponse(BaseModel):
    id: str
    name: str
    alias: str | None
    portion_text: str | None
    portion_grams: float | None
    calories: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    confidence: float | None
    user_corrected: bool


class MealResponse(BaseModel):
    id: str
    recorded_at: datetime
    recorded_tz: str
    local_date: date
    source_type: str
    meal_type: str
    total_calories: float | None
    total_protein_g: float | None
    total_carbs_g: float | None
    total_fat_g: float | None
    confidence: float | None
    source_pending_action_id: str | None
    notes: str | None
    items: list[MealItemResponse]


class MealListResponse(BaseModel):
    meals: list[MealResponse]


class BodyMetricCreateRequest(BaseModel):
    recorded_at: datetime
    recorded_tz: str = Field(default="Asia/Shanghai", max_length=64)
    source_type: BodyMetricSourceType
    weight_kg: Decimal | None = Field(default=None, ge=25, le=300)
    body_fat_percentage: Decimal | None = Field(default=None, ge=1, le=80)
    bmi: Decimal | None = Field(default=None, ge=10, le=80)
    muscle_mass_kg: Decimal | None = Field(default=None, ge=1, le=200)
    water_percentage: Decimal | None = Field(default=None, ge=1, le=90)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_pending_action_id: str | None = Field(default=None, max_length=40)


class BodyMetricPatchRequest(BaseModel):
    recorded_at: datetime | None = None
    recorded_tz: str | None = Field(default=None, max_length=64)
    source_type: BodyMetricSourceType | None = None
    weight_kg: Decimal | None = Field(default=None, ge=25, le=300)
    body_fat_percentage: Decimal | None = Field(default=None, ge=1, le=80)
    bmi: Decimal | None = Field(default=None, ge=10, le=80)
    muscle_mass_kg: Decimal | None = Field(default=None, ge=1, le=200)
    water_percentage: Decimal | None = Field(default=None, ge=1, le=90)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_pending_action_id: str | None = Field(default=None, max_length=40)


class BodyMetricResponse(BaseModel):
    id: str
    recorded_at: datetime
    recorded_tz: str
    local_date: date
    source_type: str
    weight_kg: float | None
    body_fat_percentage: float | None
    bmi: float | None
    muscle_mass_kg: float | None
    water_percentage: float | None
    confidence: float | None
    source_pending_action_id: str | None


class BodyMetricListResponse(BaseModel):
    body_metrics: list[BodyMetricResponse]
