from datetime import datetime

from app.services.time import local_date_from_utc, normalize_recorded_time


def test_normalize_recorded_time_stores_utc_and_local_date() -> None:
    recorded_at, local_date = normalize_recorded_time(
        recorded_at=datetime.fromisoformat("2026-05-01T12:30:00+08:00"),
        recorded_tz="Asia/Shanghai",
    )

    assert recorded_at.isoformat() == "2026-05-01T04:30:00"
    assert local_date.isoformat() == "2026-05-01"


def test_local_date_from_utc_keeps_same_instant_when_timezone_changes() -> None:
    local_date = local_date_from_utc(
        recorded_at_utc=datetime.fromisoformat("2026-05-01T23:30:00"),
        recorded_tz="Asia/Shanghai",
    )

    assert local_date.isoformat() == "2026-05-02"
