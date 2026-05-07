from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class PendingActionUpdateRequest(BaseModel):
    draft_payload: dict[str, Any] = Field(default_factory=dict)
    user_note: str | None = Field(default=None, max_length=2000)


class PendingActionContinuationRequest(BaseModel):
    continue_agent: bool = False
    include_agent_trace: bool = False


class PendingActionResponse(BaseModel):
    pending_action_id: str
    type: str
    status: str
    confidence: float | None
    draft_payload: dict[str, Any]
    warnings: list[dict[str, Any]]
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None


class PendingActionListResponse(BaseModel):
    pending_actions: list[PendingActionResponse]


class PendingActionCommitResponse(BaseModel):
    pending_action_id: str
    status: str
    record_type: str
    record_id: str


def decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
