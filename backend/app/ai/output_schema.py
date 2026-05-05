from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.ai.types import (
    ActionGrounding,
    ExtractionActionSpec,
    ExtractionProviderResult,
    GroundingSource,
    Intent,
)

ActionType = Literal["create_meal_record", "create_body_metric_record"]


class ExtractionWarningOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class PendingActionGroundingOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: GroundingSource
    evidence_text: str = Field(default="", max_length=4000)

    def to_grounding(self) -> ActionGrounding:
        return ActionGrounding(
            source=self.source,
            evidence_text=self.evidence_text,
        )


class PendingActionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    action_type: ActionType = Field(
        validation_alias=AliasChoices("type", "action_type"),
        serialization_alias="type",
    )
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    draft_payload: dict[str, Any]
    grounding: PendingActionGroundingOutput | None = None
    warnings: list[ExtractionWarningOutput] = Field(default_factory=list)

    def to_action_spec(self) -> ExtractionActionSpec:
        return ExtractionActionSpec(
            action_type=self.action_type,
            confidence=self.confidence,
            draft_payload=self.draft_payload,
            grounding=self.grounding.to_grounding() if self.grounding else None,
            warnings=[
                item.model_dump(mode="json", exclude_none=True)
                for item in self.warnings
            ],
        )


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assistant_text: str = Field(min_length=1, max_length=2000)
    intent: Intent
    requires_review: bool = False
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    warnings: list[ExtractionWarningOutput] = Field(default_factory=list)
    pending_actions: list[PendingActionOutput] = Field(default_factory=list, max_length=10)
    dialogue_state_patch: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_review_contract(self) -> Self:
        if self.pending_actions:
            self.requires_review = True
        if self.intent == "out_of_scope" and self.pending_actions:
            raise ValueError("out_of_scope responses must not contain pending_actions")
        return self

    def to_provider_result(self, raw_output: dict[str, Any]) -> ExtractionProviderResult:
        return ExtractionProviderResult(
            assistant_text=self.assistant_text,
            intent=self.intent,
            requires_review=self.requires_review,
            confidence=self.confidence,
            action_specs=[item.to_action_spec() for item in self.pending_actions],
            warnings=[
                item.model_dump(mode="json", exclude_none=True)
                for item in self.warnings
            ],
            dialogue_state_patch=self.dialogue_state_patch,
            raw_output=raw_output,
        )
