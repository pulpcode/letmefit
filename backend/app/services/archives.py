from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.models import BodyMetricRecord, DailyArchive, DailySummary, MealRecord


class DailyArchiveService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_archive(
        self,
        user_id: str,
        archive_date: date,
        timezone: str = "Asia/Shanghai",
    ) -> dict:
        archive = self.refresh_archive(user_id, archive_date, timezone)
        return {"archive": self._archive_response(archive)}

    def refresh_archive(
        self,
        user_id: str,
        archive_date: date,
        timezone: str = "Asia/Shanghai",
    ) -> DailyArchive:
        meals = self._meals_for_date(user_id, archive_date)
        body_metrics = self._body_metrics_for_date(user_id, archive_date)
        archive = self._find_archive(user_id, archive_date)
        if not archive:
            archive = DailyArchive(
                id=new_id("archive"),
                user_id=user_id,
                archive_date=archive_date,
            )
            self.db.add(archive)

        archive.timezone = timezone
        archive.meal_count = len(meals)
        archive.body_metric_count = len(body_metrics)
        archive.calorie_total = self._sum_optional(meal.total_calories for meal in meals)
        archive.protein_total_g = self._sum_optional(meal.total_protein_g for meal in meals)
        archive.carbs_total_g = self._sum_optional(meal.total_carbs_g for meal in meals)
        archive.fat_total_g = self._sum_optional(meal.total_fat_g for meal in meals)
        archive.completeness_score = self._completeness_score(
            meal_count=archive.meal_count,
            body_metric_count=archive.body_metric_count,
        )
        archive.last_calculated_at = utc_now()
        self.db.commit()
        self.db.refresh(archive)
        return archive

    def _find_archive(self, user_id: str, archive_date: date) -> DailyArchive | None:
        return self.db.scalar(
            select(DailyArchive).where(
                DailyArchive.user_id == user_id,
                DailyArchive.archive_date == archive_date,
            )
        )

    def _meals_for_date(self, user_id: str, archive_date: date) -> list[MealRecord]:
        return list(
            self.db.scalars(
                select(MealRecord)
                .where(
                    MealRecord.user_id == user_id,
                    MealRecord.local_date == archive_date,
                    MealRecord.deleted_at.is_(None),
                )
                .order_by(MealRecord.recorded_at.asc())
            )
        )

    def _body_metrics_for_date(
        self,
        user_id: str,
        archive_date: date,
    ) -> list[BodyMetricRecord]:
        return list(
            self.db.scalars(
                select(BodyMetricRecord)
                .where(
                    BodyMetricRecord.user_id == user_id,
                    BodyMetricRecord.local_date == archive_date,
                    BodyMetricRecord.deleted_at.is_(None),
                )
                .order_by(BodyMetricRecord.recorded_at.asc())
            )
        )

    def _sum_optional(self, values) -> Decimal | None:
        present = [value for value in values if value is not None]
        if not present:
            return None
        return sum(present, Decimal("0"))

    def _completeness_score(self, meal_count: int, body_metric_count: int) -> Decimal:
        meal_score = min(meal_count, 3) / 3 * 0.7
        body_metric_score = 0.3 if body_metric_count > 0 else 0
        return Decimal(str(round(min(meal_score + body_metric_score, 1.0), 4)))

    def _archive_response(self, archive: DailyArchive) -> dict:
        return {
            "id": archive.id,
            "date": archive.archive_date,
            "timezone": archive.timezone,
            "meal_count": archive.meal_count,
            "body_metric_count": archive.body_metric_count,
            "calorie_total": self._number(archive.calorie_total),
            "protein_total_g": self._number(archive.protein_total_g),
            "carbs_total_g": self._number(archive.carbs_total_g),
            "fat_total_g": self._number(archive.fat_total_g),
            "completeness_score": self._number(archive.completeness_score) or 0.0,
            "last_calculated_at": archive.last_calculated_at,
        }

    def _number(self, value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(value)


class DailySummaryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.archive_service = DailyArchiveService(db)

    def generate_summary(
        self,
        user_id: str,
        summary_date: date,
        timezone: str = "Asia/Shanghai",
    ) -> dict:
        archive = self.archive_service.refresh_archive(user_id, summary_date, timezone)
        summary_text, suggestions = self._compose_summary(archive)
        summary = self._find_summary(user_id, summary_date)
        if not summary:
            summary = DailySummary(
                id=new_id("summary"),
                user_id=user_id,
                summary_date=summary_date,
            )
            self.db.add(summary)

        summary.archive_id = archive.id
        summary.summary_text = summary_text
        summary.suggestions_json = suggestions
        summary.model_provider = "local_rule"
        summary.model_name = "daily-summary-v1"
        summary.generation_status = "generated"
        self.db.commit()
        self.db.refresh(summary)
        return {
            "summary": self._summary_response(summary, archive),
        }

    def _find_summary(self, user_id: str, summary_date: date) -> DailySummary | None:
        return self.db.scalar(
            select(DailySummary).where(
                DailySummary.user_id == user_id,
                DailySummary.summary_date == summary_date,
            )
        )

    def _compose_summary(self, archive: DailyArchive) -> tuple[str, list[str]]:
        meal_count = archive.meal_count
        body_metric_count = archive.body_metric_count
        calorie_total = self.archive_service._number(archive.calorie_total)
        protein_total = self.archive_service._number(archive.protein_total_g)

        if meal_count == 0 and body_metric_count == 0:
            return (
                "今天还没有形成有效记录。",
                ["先补一条餐食或身体指标记录，再生成更有参考价值的总结。"],
            )

        parts = [f"今天记录了 {meal_count} 条餐食"]
        if calorie_total is not None:
            parts.append(f"总热量约 {calorie_total:.0f} kcal")
        if protein_total is not None:
            parts.append(f"蛋白质约 {protein_total:.0f} g")
        if body_metric_count:
            parts.append(f"身体指标 {body_metric_count} 条")
        summary_text = "，".join(parts) + "。"

        suggestions = []
        if meal_count < 3:
            suggestions.append("餐食记录还不完整，建议补齐三餐后再看全天趋势。")
        if protein_total is not None and protein_total < 60:
            suggestions.append("蛋白质记录偏低，下一餐可优先补充瘦肉、蛋、奶或豆制品。")
        if body_metric_count == 0:
            suggestions.append("可以补充一次体重或体脂记录，便于观察阶段变化。")
        if not suggestions:
            suggestions.append("今天记录较完整，后续可以继续保持相同记录节奏。")
        return summary_text, suggestions[:3]

    def _summary_response(self, summary: DailySummary, archive: DailyArchive) -> dict:
        return {
            "id": summary.id,
            "date": summary.summary_date,
            "archive_id": archive.id,
            "calorie_total": self.archive_service._number(archive.calorie_total),
            "protein_total_g": self.archive_service._number(archive.protein_total_g),
            "carbs_total_g": self.archive_service._number(archive.carbs_total_g),
            "fat_total_g": self.archive_service._number(archive.fat_total_g),
            "meal_count": archive.meal_count,
            "body_metric_count": archive.body_metric_count,
            "summary_text": summary.summary_text,
            "suggestions": summary.suggestions_json,
            "completeness_score": self.archive_service._number(archive.completeness_score) or 0.0,
            "generation_status": summary.generation_status,
        }


def get_daily_archive_service(
    db: Annotated[Session, Depends(get_db)],
) -> DailyArchiveService:
    return DailyArchiveService(db)


def get_daily_summary_service(
    db: Annotated[Session, Depends(get_db)],
) -> DailySummaryService:
    return DailySummaryService(db)
