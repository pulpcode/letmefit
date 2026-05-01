import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.models import AgentExtraction, AgentPendingAction
from app.schemas.conversation import MessageContentItem
from app.schemas.pending_action import decimal_to_float


class MockExtractionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def process_message(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        content: list[MessageContentItem],
    ) -> dict:
        text = self._joined_text(content)
        input_types = self._input_types(content)
        if self._is_out_of_scope(text):
            return {
                "assistant_text": (
                    "这个问题可能涉及医疗诊断或治疗建议，我不能替你判断。"
                    "可以聊聊一般健身记录、饮食习惯和训练安排。"
                ),
                "intent": "out_of_scope",
                "requires_review": False,
                "pending_actions": [],
            }

        action_specs = self._action_specs(text, content)
        if not action_specs:
            return {
                "assistant_text": (
                    "我可以帮你记录饮食、体重和训练相关信息。"
                    "你可以继续补充具体内容。"
                ),
                "intent": "answer_fitness_question",
                "requires_review": False,
                "pending_actions": [],
            }

        extraction = AgentExtraction(
            id=new_id("ext"),
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_types_json=input_types,
            intent="fitness_record",
            confidence=Decimal("0.60"),
            requires_confirmation=True,
            raw_output_json={"mock": True, "text": text},
            warnings_json=[],
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
                action_spec=action_spec,
            )
            for action_spec in action_specs
        ]
        assistant_text = self._assistant_text(pending_actions)
        return {
            "assistant_text": assistant_text,
            "intent": "fitness_record",
            "requires_review": True,
            "pending_actions": [self._pending_response(action) for action in pending_actions],
        }

    def _action_specs(self, text: str, content: list[MessageContentItem]) -> list[dict[str, Any]]:
        specs = []
        lowered = text.lower()
        has_image = any(item.type == "image" for item in content)
        meal_keywords = ("早餐", "午餐", "晚餐", "加餐", "吃", "餐", "meal", "lunch", "dinner")
        if has_image or any(keyword in lowered for keyword in meal_keywords):
            specs.append(self._meal_spec(lowered, has_image))

        body_keywords = ("体重", "体脂", "bmi", "weight", "公斤", "kg", "斤")
        if any(keyword in lowered for keyword in body_keywords):
            specs.append(self._body_metric_spec(lowered))
        return specs

    def _meal_spec(self, text: str, has_image: bool) -> dict[str, Any]:
        meal_type = "unknown"
        if "早餐" in text or "breakfast" in text:
            meal_type = "breakfast"
        elif "午餐" in text or "lunch" in text:
            meal_type = "lunch"
        elif "晚餐" in text or "dinner" in text:
            meal_type = "dinner"
        elif "加餐" in text or "snack" in text:
            meal_type = "snack"

        return {
            "action_type": "create_meal_record",
            "confidence": Decimal("0.45") if has_image else Decimal("0.50"),
            "draft_payload": {
                "recorded_at": self._now_iso(),
                "source_type": "photo" if has_image else "text",
                "meal_type": meal_type,
                "items": [
                    {
                        "name": "待确认食物",
                        "portion_text": "待确认",
                        "confidence": 0.3,
                        "user_corrected": False,
                    }
                ],
                "confidence": 0.45 if has_image else 0.5,
            },
            "warnings": [
                {
                    "field": "items",
                    "reason": "mock_extraction_requires_user_confirmation",
                }
            ],
        }

    def _body_metric_spec(self, text: str) -> dict[str, Any]:
        weight_kg = self._extract_weight_kg(text)
        draft_payload: dict[str, Any] = {
            "recorded_at": self._now_iso(),
            "source_type": "text",
            "confidence": 0.65 if weight_kg is not None else 0.35,
        }
        warnings = []
        if weight_kg is not None:
            draft_payload["weight_kg"] = weight_kg
        else:
            warnings.append({"field": "weight_kg", "reason": "missing_or_low_confidence"})

        return {
            "action_type": "create_body_metric_record",
            "confidence": Decimal("0.65") if weight_kg is not None else Decimal("0.35"),
            "draft_payload": draft_payload,
            "warnings": warnings,
        }

    def _create_pending_action(
        self,
        user_id: str,
        conversation_id: str,
        message_id: str,
        extraction_id: str,
        action_spec: dict[str, Any],
    ) -> AgentPendingAction:
        action = AgentPendingAction(
            id=new_id("pa"),
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=message_id,
            extraction_id=extraction_id,
            action_type=action_spec["action_type"],
            status="pending_confirmation",
            draft_payload_json=action_spec["draft_payload"],
            warnings_json=action_spec["warnings"],
            confidence=action_spec["confidence"],
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _assistant_text(self, pending_actions: list[AgentPendingAction]) -> str:
        if len(pending_actions) == 1 and pending_actions[0].action_type == "create_meal_record":
            return "我先整理成一条餐食记录草稿，请确认或修改后再保存。"
        if (
            len(pending_actions) == 1
            and pending_actions[0].action_type == "create_body_metric_record"
        ):
            return "我先整理成一条身体指标草稿，请确认或修改后再保存。"
        return "我整理出了几个待确认动作，请逐项确认或修改后再保存。"

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

    def _joined_text(self, content: list[MessageContentItem]) -> str:
        return " ".join(item.text or "" for item in content if item.type == "text").strip()

    def _input_types(self, content: list[MessageContentItem]) -> list[str]:
        return sorted({item.type for item in content})

    def _extract_weight_kg(self, text: str) -> float | None:
        kg_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|公斤)", text, flags=re.IGNORECASE)
        if kg_match:
            return float(kg_match.group(1))
        jin_match = re.search(r"(\d+(?:\.\d+)?)\s*斤", text)
        if jin_match:
            return float(jin_match.group(1)) / 2
        return None

    def _is_out_of_scope(self, text: str) -> bool:
        risky_keywords = ("诊断", "治疗", "处方", "糖尿病", "高血压", "疾病", "用药")
        return any(keyword in text for keyword in risky_keywords)

    def _now_iso(self) -> str:
        return datetime.now(UTC).astimezone().isoformat()
