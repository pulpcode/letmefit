from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import BodyMetricRecord
from app.schemas.records import BodyMetricCreateRequest, BodyMetricPatchRequest
from app.services.time import local_date_from_utc, normalize_recorded_time

BODY_METRIC_FIELDS = (
    "source_type",
    "weight_kg",
    "body_fat_percentage",
    "bmi",
    "muscle_mass_kg",
    "water_percentage",
    "confidence",
    "source_pending_action_id",
)


class BodyMetricService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_body_metrics(
        self,
        user_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        query = select(BodyMetricRecord).where(
            BodyMetricRecord.user_id == user_id,
            BodyMetricRecord.deleted_at.is_(None),
        )
        if date_from:
            query = query.where(BodyMetricRecord.local_date >= date_from)
        if date_to:
            query = query.where(BodyMetricRecord.local_date <= date_to)
        records = list(self.db.scalars(query.order_by(BodyMetricRecord.recorded_at.desc())))
        return {"body_metrics": [self._response(record) for record in records]}

    def get_body_metric(self, user_id: str, body_metric_id: str) -> dict:
        return self._response(self._get_owned_body_metric(user_id, body_metric_id))

    def create_body_metric(self, user_id: str, payload: BodyMetricCreateRequest) -> dict:
        recorded_at, local_date = normalize_recorded_time(payload.recorded_at, payload.recorded_tz)
        record = BodyMetricRecord(
            id=new_id("bm"),
            user_id=user_id,
            recorded_at=recorded_at,
            recorded_tz=payload.recorded_tz,
            local_date=local_date,
            source_type=payload.source_type,
            weight_kg=payload.weight_kg,
            body_fat_percentage=payload.body_fat_percentage,
            bmi=payload.bmi,
            muscle_mass_kg=payload.muscle_mass_kg,
            water_percentage=payload.water_percentage,
            confidence=payload.confidence,
            source_pending_action_id=payload.source_pending_action_id,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return self._response(record)

    def update_body_metric(
        self,
        user_id: str,
        body_metric_id: str,
        payload: BodyMetricPatchRequest,
    ) -> dict:
        record = self._get_owned_body_metric(user_id, body_metric_id)
        recorded_tz = payload.recorded_tz or record.recorded_tz
        if payload.recorded_at is not None:
            record.recorded_at, record.local_date = normalize_recorded_time(
                payload.recorded_at,
                recorded_tz,
            )
            record.recorded_tz = recorded_tz
        elif payload.recorded_tz is not None:
            record.local_date = local_date_from_utc(record.recorded_at, recorded_tz)
            record.recorded_tz = recorded_tz

        for field in BODY_METRIC_FIELDS:
            if field in payload.model_fields_set:
                setattr(record, field, getattr(payload, field))

        self.db.commit()
        self.db.refresh(record)
        return self._response(record)

    def delete_body_metric(self, user_id: str, body_metric_id: str) -> dict:
        record = self._get_owned_body_metric(user_id, body_metric_id)
        record.deleted_at = utc_now()
        self.db.commit()
        return {"success": True}

    def _get_owned_body_metric(self, user_id: str, body_metric_id: str) -> BodyMetricRecord:
        record = self.db.scalar(
            select(BodyMetricRecord).where(
                BodyMetricRecord.id == body_metric_id,
                BodyMetricRecord.user_id == user_id,
                BodyMetricRecord.deleted_at.is_(None),
            )
        )
        if not record:
            raise AppError("RESOURCE_NOT_FOUND", "身体指标记录不存在", status_code=404)
        return record

    def _response(self, record: BodyMetricRecord) -> dict:
        return {
            "id": record.id,
            "recorded_at": record.recorded_at,
            "recorded_tz": record.recorded_tz,
            "local_date": record.local_date,
            "source_type": record.source_type,
            "weight_kg": self._number(record.weight_kg),
            "body_fat_percentage": self._number(record.body_fat_percentage),
            "bmi": self._number(record.bmi),
            "muscle_mass_kg": self._number(record.muscle_mass_kg),
            "water_percentage": self._number(record.water_percentage),
            "confidence": self._number(record.confidence),
            "source_pending_action_id": record.source_pending_action_id,
        }

    def _number(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)


def get_body_metric_service(
    db: Annotated[Session, Depends(get_db)],
) -> BodyMetricService:
    return BodyMetricService(db)
