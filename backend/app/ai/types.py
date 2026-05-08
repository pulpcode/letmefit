from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from app.schemas.conversation import MessageContentItem

Intent = Literal["fitness_record", "answer_fitness_question", "out_of_scope"]
GroundingSource = Literal[
    "user_current_turn",
    "assistant_generated",
    "current_user_message",
    "normalized_media_text",
    "recent_user_message",
    "active_pending_action",
    "tool_result",
    "confirmed_record",
    "assistant_plan",
    "model_inference",
]
ToolName = Literal[
    "propose_meal_record",
    "propose_body_metric_record",
    "propose_workout_record",
    "update_pending_action",
    "commit_pending_action",
    "commit_pending_actions",
    "discard_pending_actions",
    "query_meal_records",
    "query_body_metric_records",
]
RECORD_TOOL_NAMES = {
    "propose_meal_record",
    "propose_body_metric_record",
    "propose_workout_record",
}
READ_ONLY_TOOL_NAMES = {"query_meal_records", "query_body_metric_records"}
PENDING_ACTION_TOOL_NAMES = {
    "update_pending_action",
    "commit_pending_action",
    "commit_pending_actions",
    "discard_pending_actions",
}
HUMAN_CONFIRMATION_TOOL_NAMES = RECORD_TOOL_NAMES


@dataclass(frozen=True)
class ExtractionInput:
    user_id: str
    conversation_id: str
    message_id: str
    content: list[MessageContentItem]
    context: dict[str, Any] = field(default_factory=dict)
    prior_turns: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ActionGrounding:
    source: GroundingSource
    evidence_text: str
    source_id: str | None = None
    confidence: Decimal | None = None


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
        if self.name == "propose_workout_record":
            return "create_workout_record"
        if self.name == "update_pending_action":
            return "update_pending_action"
        if self.name == "commit_pending_action":
            return "commit_pending_action"
        if self.name == "commit_pending_actions":
            return "commit_pending_actions"
        if self.name == "discard_pending_actions":
            return "discard_pending_actions"
        if self.name == "query_meal_records":
            return "query_meal_records"
        if self.name == "query_body_metric_records":
            return "query_body_metric_records"
        raise ValueError(f"Unsupported tool call: {self.name}")

    @property
    def is_record_tool(self) -> bool:
        return self.name in RECORD_TOOL_NAMES

    @property
    def is_read_only_tool(self) -> bool:
        return self.name in READ_ONLY_TOOL_NAMES

    @property
    def is_pending_action_tool(self) -> bool:
        return self.name in PENDING_ACTION_TOOL_NAMES


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
