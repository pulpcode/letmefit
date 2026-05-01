from typing import Any

from sqlalchemy import String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

ID_LENGTH = 40
HASH_LENGTH = 128
STATUS_LENGTH = 32

datetime_type = mysql.DATETIME(fsp=6)
json_type = mysql.JSON


def id_column() -> Mapped[str]:
    return mapped_column(String(ID_LENGTH), primary_key=True)


def utc_datetime(nullable: bool = True) -> Mapped[Any]:
    return mapped_column(datetime_type, nullable=nullable)


class TimestampMixin:
    created_at: Mapped[Any] = mapped_column(
        datetime_type,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )
    updated_at: Mapped[Any] = mapped_column(
        datetime_type,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )
