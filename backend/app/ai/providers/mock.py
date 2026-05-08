import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.ai.providers.base import ExtractionProvider
from app.ai.types import (
    ActionGrounding,
    ExtractionInput,
    ExtractionProviderResult,
    ExtractionToolCall,
)
from app.core.config import Settings, get_settings
from app.schemas.conversation import MessageContentItem


class MockExtractionProvider(ExtractionProvider):
    provider_name = "mock"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, payload: ExtractionInput) -> ExtractionProviderResult:
        text = self._joined_text(payload.content)
        if payload.prior_turns:
            return ExtractionProviderResult(
                assistant_text="我已根据工具结果完成处理。",
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.70"),
                raw_output={"mock": True, "text": text, "agent_loop_final": True},
            )
        if self._is_out_of_scope(text):
            return ExtractionProviderResult(
                assistant_text=(
                    "这个问题可能涉及医疗诊断或治疗建议，我不能替你判断。"
                    "可以聊聊一般健身记录、饮食习惯和训练安排。"
                ),
                intent="out_of_scope",
                requires_review=False,
                confidence=Decimal("0.80"),
                raw_output={"mock": True, "text": text},
            )

        tool_calls = self._tool_calls(text, payload.content)
        if not tool_calls:
            return ExtractionProviderResult(
                assistant_text=(
                    "我可以帮你记录饮食、体重和训练相关信息。"
                    "你可以继续补充具体内容。"
                ),
                intent="answer_fitness_question",
                requires_review=False,
                confidence=Decimal("0.70"),
                raw_output={"mock": True, "text": text},
            )

        return ExtractionProviderResult(
            assistant_text=self._assistant_text(tool_calls),
            intent="fitness_record",
            requires_review=True,
            confidence=Decimal("0.60"),
            tool_calls=tool_calls,
            raw_output={"mock": True, "text": text},
        )

    def _tool_calls(
        self,
        text: str,
        content: list[MessageContentItem],
    ) -> list[ExtractionToolCall]:
        tool_calls = []
        lowered = text.lower()
        has_image = any(item.type == "image" for item in content)
        meal_keywords = ("早餐", "午餐", "晚餐", "加餐", "吃", "餐", "meal", "lunch", "dinner")
        if has_image or any(keyword in lowered for keyword in meal_keywords):
            tool_calls.append(self._meal_tool_call(lowered, has_image, text))

        body_keywords = ("体重", "体脂", "bmi", "weight", "公斤", "kg", "斤")
        if any(keyword in lowered for keyword in body_keywords):
            tool_calls.append(self._body_metric_tool_call(lowered, text))
        return tool_calls

    def _meal_tool_call(
        self,
        text: str,
        has_image: bool,
        evidence_text: str,
    ) -> ExtractionToolCall:
        meal_type = "unknown"
        if "早餐" in text or "breakfast" in text:
            meal_type = "breakfast"
        elif "午餐" in text or "lunch" in text:
            meal_type = "lunch"
        elif "晚餐" in text or "dinner" in text:
            meal_type = "dinner"
        elif "加餐" in text or "snack" in text:
            meal_type = "snack"

        confidence = Decimal("0.45") if has_image else Decimal("0.50")
        items = self._extract_gram_items(text)
        if items and not has_image:
            confidence = Decimal("0.90")
            warnings = []
        else:
            items = [
                {
                    "name": "待确认食物",
                    "portion_text": "待确认",
                    "confidence": 0.3,
                    "user_corrected": False,
                }
            ]
            warnings = [
                {
                    "field": "items",
                    "reason": "mock_extraction_requires_user_confirmation",
                }
            ]
        return ExtractionToolCall(
            name="propose_meal_record",
            confidence=confidence,
            arguments={
                "recorded_at": self._now_iso(),
                "source_type": "photo" if has_image else "text",
                "meal_type": meal_type,
                "items": items,
                "confidence": float(confidence),
            },
            grounding=self._grounding(evidence_text),
            warnings=warnings,
        )

    def _body_metric_tool_call(self, text: str, evidence_text: str) -> ExtractionToolCall:
        weight_kg = self._extract_weight_kg(text)
        confidence = Decimal("0.90") if weight_kg is not None else Decimal("0.35")
        draft_payload: dict[str, Any] = {
            "recorded_at": self._now_iso(),
            "source_type": "text",
            "confidence": float(confidence),
        }
        warnings = []
        if weight_kg is not None:
            draft_payload["weight_kg"] = weight_kg
        else:
            warnings.append({"field": "weight_kg", "reason": "missing_or_low_confidence"})

        return ExtractionToolCall(
            name="propose_body_metric_record",
            confidence=confidence,
            arguments=draft_payload,
            grounding=self._grounding(evidence_text),
            warnings=warnings,
        )

    def _grounding(self, evidence_text: str) -> ActionGrounding | None:
        if not evidence_text.strip():
            return None
        return ActionGrounding(source="user_current_turn", evidence_text=evidence_text)

    def _extract_gram_items(self, text: str) -> list[dict[str, Any]]:
        items = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:克|g)\s*([a-zA-Z\u4e00-\u9fff]+)", text):
            grams = float(match.group(1))
            name = self._clean_food_name(match.group(2))
            if name:
                items.append(
                    {
                        "name": name,
                        "portion_text": f"{grams:g}g",
                        "portion_grams": grams,
                        "confidence": 0.9,
                        "user_corrected": False,
                    }
                )
        return items

    def _clean_food_name(self, value: str) -> str:
        value = value.strip(" ，,。.;；、")
        for prefix in ("的",):
            if value.startswith(prefix):
                value = value[len(prefix) :]
        for suffix in ("和", "以及", "还有"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value.strip(" ，,。.;；、")

    def _assistant_text(self, tool_calls: list[ExtractionToolCall]) -> str:
        if len(tool_calls) == 1 and tool_calls[0].name == "propose_meal_record":
            return "我先整理成一条餐食记录草稿，请确认或修改后再保存。"
        if len(tool_calls) == 1 and tool_calls[0].name == "propose_body_metric_record":
            return "我先整理成一条身体指标草稿，请确认或修改后再保存。"
        return "我整理出了几个待确认动作，请逐项确认或修改后再保存。"

    def _joined_text(self, content: list[MessageContentItem]) -> str:
        return " ".join(item.text or "" for item in content if item.type == "text").strip()

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
