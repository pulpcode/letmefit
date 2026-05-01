from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ProfileUpsertRequest(BaseModel):
    age: int | None = Field(default=None, ge=18, le=100)
    sex: Literal["male", "female", "other", "unspecified"] | None = None
    height_cm: Decimal | None = Field(default=None, ge=80, le=250)
    current_weight_kg: Decimal | None = Field(default=None, ge=25, le=300)
    target_weight_kg: Decimal | None = Field(default=None, ge=25, le=300)
    activity_level: Literal[
        "sedentary",
        "light",
        "moderate",
        "active",
        "very_active",
    ] | None = None
    goal_type: Literal[
        "fat_loss",
        "muscle_gain",
        "maintenance",
        "fitness",
    ] | None = None


class UserProfileResponse(BaseModel):
    id: str
    age: int | None
    sex: str | None
    height_cm: float | None
    current_weight_kg: float | None
    target_weight_kg: float | None
    activity_level: str | None
    goal_type: str | None
    completed_at: datetime | None


class ProfileResponse(BaseModel):
    profile: UserProfileResponse | None
    profile_completed: bool
