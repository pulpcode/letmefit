from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import AppError


def get_timezone(recorded_tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(recorded_tz)
    except ZoneInfoNotFoundError as exc:
        raise AppError("VALIDATION_ERROR", "记录时区不正确", status_code=422) from exc


def normalize_recorded_time(
    recorded_at: datetime,
    recorded_tz: str = "Asia/Shanghai",
) -> tuple[datetime, date]:
    timezone = get_timezone(recorded_tz)

    if recorded_at.tzinfo is None:
        local_time = recorded_at.replace(tzinfo=timezone)
    else:
        local_time = recorded_at.astimezone(timezone)

    utc_time = local_time.astimezone(UTC).replace(tzinfo=None)
    return utc_time, local_time.date()


def local_date_from_utc(recorded_at_utc: datetime, recorded_tz: str) -> date:
    timezone = get_timezone(recorded_tz)
    if recorded_at_utc.tzinfo is None:
        utc_time = recorded_at_utc.replace(tzinfo=UTC)
    else:
        utc_time = recorded_at_utc.astimezone(UTC)
    return utc_time.astimezone(timezone).date()
