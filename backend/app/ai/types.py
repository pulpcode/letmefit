from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.schemas.conversation import MessageContentItem

Intent = Literal["fitness_record", "answer_fitness_question", "out_of_scope"]


@dataclass(frozen=True)
class ExtractionInput:
    user_id: str
    conversation_id: str
    message_id: str
    content: list[MessageContentItem]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionActionSpec:
    action_type: str
    confidence: Decimal | None
    draft_payload: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionProviderResult:
    assistant_text: str
    intent: Intent
    requires_review: bool
    confidence: Decimal | None
    action_specs: list[ExtractionActionSpec] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    dialogue_state_patch: dict[str, Any] | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)
