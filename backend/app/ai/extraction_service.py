from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai.draft_normalizer import normalize_pending_action_draft
from app.ai.providers import ExtractionProvider, get_extraction_provider
from app.ai.types import ExtractionInput, ExtractionProviderResult
from app.auth.security import new_id, utc_now
from app.core.config import Settings, get_settings
from app.models import AgentExtraction, AgentPendingAction
from app.schemas.conversation import MessageContentItem
from app.schemas.pending_action import decimal_to_float


class ExtractionService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        provider: ExtractionProvider | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.provider = provider or get_extraction_provider(self.settings)

    def process_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
        context: dict | None = None,
    ) -> dict:
        provider_result = self.provider.extract(
            ExtractionInput(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
                context=context or {},
            )
        )
        if not provider_result.action_specs:
            return self._result_response(provider_result, [])

        extraction = AgentExtraction(
            id=new_id("ext"),
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_types_json=self._input_types(content),
            intent=provider_result.intent,
            confidence=provider_result.confidence,
            requires_confirmation=provider_result.requires_review,
            raw_output_json=provider_result.raw_output,
            warnings_json=provider_result.warnings,
            status="succeeded",
            created_at=utc_now(),
        )
        self.db.add(extraction)
        self.db.flush()

        pending_actions = [
            self._create_pending_action(
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                extraction_id=extraction.id,
                provider_result=provider_result,
                action_spec=action_spec,
            )
            for action_spec in provider_result.action_specs
        ]
        return self._result_response(provider_result, pending_actions)

    def _create_pending_action(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        extraction_id: str,
        provider_result: ExtractionProviderResult,
        action_spec,
    ) -> AgentPendingAction:
        action = AgentPendingAction(
            id=new_id("pa"),
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
            extraction_id=extraction_id,
            action_type=action_spec.action_type,
            status="pending_confirmation",
            draft_payload_json=normalize_pending_action_draft(
                action_spec.action_type,
                action_spec.draft_payload,
            ),
            warnings_json=action_spec.warnings,
            confidence=action_spec.confidence or provider_result.confidence or Decimal("0"),
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _result_response(
        self,
        provider_result: ExtractionProviderResult,
        pending_actions: list[AgentPendingAction],
    ) -> dict:
        return {
            "assistant_text": provider_result.assistant_text,
            "intent": provider_result.intent,
            "requires_review": provider_result.requires_review,
            "pending_actions": [self._pending_response(action) for action in pending_actions],
        }

    def _pending_response(self, action: AgentPendingAction) -> dict:
        return {
            "pending_action_id": action.id,
            "type": action.action_type,
            "status": action.status,
            "confidence": decimal_to_float(action.confidence),
            "draft_payload": action.draft_payload_json,
            "warnings": action.warnings_json or [],
            "created_at": action.created_at,
            "updated_at": action.updated_at,
        }

    def _input_types(self, content: list[MessageContentItem]) -> list[str]:
        return sorted({item.type for item in content})
