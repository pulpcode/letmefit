from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.models import UserProfile
from app.schemas.profile import ProfileUpsertRequest

PROFILE_FIELDS = (
    "age",
    "sex",
    "height_cm",
    "current_weight_kg",
    "target_weight_kg",
    "activity_level",
    "goal_type",
)

PROFILE_REQUIRED_FIELDS = (
    "age",
    "sex",
    "height_cm",
    "current_weight_kg",
    "activity_level",
    "goal_type",
)


class ProfileService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_profile(self, user_id: str) -> dict:
        profile = self._find_profile(user_id)
        return self._response(profile)

    def upsert_profile(self, user_id: str, payload: ProfileUpsertRequest) -> dict:
        profile = self._find_profile(user_id)
        if not profile:
            profile = UserProfile(id=new_id("profile"), user_id=user_id)
            self.db.add(profile)

        for field in PROFILE_FIELDS:
            if field in payload.model_fields_set:
                setattr(profile, field, getattr(payload, field))

        profile.completed_at = utc_now() if self._is_complete(profile) else None
        self.db.commit()
        self.db.refresh(profile)
        return self._response(profile)

    def _find_profile(self, user_id: str) -> UserProfile | None:
        return self.db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))

    def _response(self, profile: UserProfile | None) -> dict:
        if not profile:
            return {
                "profile": None,
                "profile_completed": False,
            }

        return {
            "profile": {
                "id": profile.id,
                "age": profile.age,
                "sex": profile.sex,
                "height_cm": self._number(profile.height_cm),
                "current_weight_kg": self._number(profile.current_weight_kg),
                "target_weight_kg": self._number(profile.target_weight_kg),
                "activity_level": profile.activity_level,
                "goal_type": profile.goal_type,
                "completed_at": profile.completed_at,
            },
            "profile_completed": bool(profile.completed_at),
        }

    def _is_complete(self, profile: UserProfile) -> bool:
        return all(getattr(profile, field) is not None for field in PROFILE_REQUIRED_FIELDS)

    def _number(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)


def get_profile_service(db: Annotated[Session, Depends(get_db)]) -> ProfileService:
    return ProfileService(db)
