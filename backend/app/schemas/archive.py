from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyArchiveResponse(BaseModel):
    id: str
    date: date
    timezone: str
    meal_count: int
    body_metric_count: int
    calorie_total: float | None
    protein_total_g: float | None
    carbs_total_g: float | None
    fat_total_g: float | None
    completeness_score: float
    last_calculated_at: datetime


class SummaryGenerateRequest(BaseModel):
    date: date
    timezone: str = Field(default="Asia/Shanghai", max_length=64)


class DailySummaryResponse(BaseModel):
    id: str
    date: date
    archive_id: str
    calorie_total: float | None
    protein_total_g: float | None
    carbs_total_g: float | None
    fat_total_g: float | None
    meal_count: int
    body_metric_count: int
    summary_text: str
    suggestions: list[str]
    completeness_score: float
    generation_status: str
