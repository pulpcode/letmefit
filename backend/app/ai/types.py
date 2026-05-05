from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.schemas.conversation import MessageContentItem

Intent = Literal["fitness_record", "answer_fitness_question", "out_of_scope"]
GroundingSource = Literal["user_current_turn", "assistant_generated"]
ToolName = Literal["propose_meal_record", "propose_body_metric_record"]


@dataclass(frozen=True)
class ExtractionInput:
    user_id: str
    conversation_id: str
    message_id: str
    content: list[MessageContentItem]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionGrounding:
    source: GroundingSource
    evidence_text: str


@dataclass(frozen=True)
class ExtractionActionSpec:
    action_type: str
    confidence: Decimal | None
    draft_payload: dict[str, Any]
    grounding: ActionGrounding | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionToolCall:
    name: ToolName
    arguments: dict[str, Any]
    confidence: Decimal | None = None
    grounding: ActionGrounding | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_action_spec(self) -> ExtractionActionSpec:
        return ExtractionActionSpec(
            action_type=self.action_type,
            confidence=self.confidence,
            draft_payload=self.arguments,
            grounding=self.grounding,
            warnings=self.warnings,
        )

    @property
    def action_type(self) -> str:
        if self.name == "propose_meal_record":
            return "create_meal_record"
        if self.name == "propose_body_metric_record":
            return "create_body_metric_record"
        raise ValueError(f"Unsupported tool call: {self.name}")


@dataclass(frozen=True)
class ExtractionProviderResult:
    assistant_text: str
    intent: Intent
    requires_review: bool
    confidence: Decimal | None
    tool_calls: list[ExtractionToolCall] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    dialogue_state_patch: dict[str, Any] | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)
