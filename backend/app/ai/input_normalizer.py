import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

from openai import OpenAI, OpenAIError

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models import UploadFile
from app.schemas.conversation import MessageContentItem


@dataclass(frozen=True)
class MediaInput:
    file_id: str
    type: str
    mime_type: str
    storage_provider: str
    client_local_ref: str | None
    bucket: str | None
    object_key: str | None
    source: str
    duration_seconds: int | None = None


@dataclass(frozen=True)
class SpeechToTextResult:
    transcript: str | None = None
    language: str | None = None
    confidence: float | None = None
    provider: str = "mock"
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ImageUnderstandingResult:
    description: str | None = None
    provider: str = "mock"
    confidence: float | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizedInput:
    content: list[MessageContentItem]
    context: dict[str, Any]


class SpeechToTextProvider(Protocol):
    provider_name: str

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        raise NotImplementedError


class ImageUnderstandingProvider(Protocol):
    provider_name: str

    def describe(self, media: MediaInput) -> ImageUnderstandingResult:
        raise NotImplementedError


class JsonHttpClient(Protocol):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def get_json(self, url: str) -> dict[str, Any]:
        raise NotImplementedError


class UrlLibJsonHttpClient:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class MockSpeechToTextProvider:
    provider_name = "mock"

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        return SpeechToTextResult(
            transcript=None,
            provider=self.provider_name,
            warnings=[
                {
                    "field": "audio",
                    "reason": "asr_provider_mock_no_transcript",
                    "file_id": media.file_id,
                }
            ],
        )


class DashScopeRecordingSpeechToTextProvider:
    provider_name = "dashscope_recording"

    def __init__(
        self,
        settings: Settings,
        http_client: JsonHttpClient | None = None,
        sleep_func=time.sleep,
    ) -> None:
        self.settings = settings
        self.http_client = http_client or UrlLibJsonHttpClient(settings.ai_timeout_seconds)
        self.sleep_func = sleep_func

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        api_key = self.settings.dashscope_api_key or self.settings.bailian_api_key
        if not api_key:
            return self._warning_result(media, "asr_api_key_missing")

        file_url = self._media_url(media)
        if not file_url:
            return self._warning_result(media, "asr_requires_public_or_oss_url")

        try:
            task_id = self._submit_task(api_key, file_url)
            task_output = self._wait_for_task(api_key, task_id)
            transcription_url = self._transcription_url(task_output)
            if not transcription_url:
                return self._warning_result(media, "asr_transcription_url_missing", task_id)
            transcript_data = self.http_client.get_json(transcription_url)
            transcript = self._transcript_text(transcript_data)
        except (KeyError, TypeError, ValueError, URLError, TimeoutError) as exc:
            return self._warning_result(
                media,
                "asr_provider_error",
                error=f"{exc.__class__.__name__}: {exc}",
            )

        if not transcript:
            return self._warning_result(media, "asr_empty_transcript", task_id)

        return SpeechToTextResult(
            transcript=transcript,
            language=None,
            confidence=None,
            provider=self.provider_name,
        )

    def _submit_task(self, api_key: str, file_url: str) -> str:
        payload = {
            "model": self.settings.dashscope_asr_model,
            "input": {"file_urls": [file_url]},
            "parameters": {
                "channel_id": [0],
                "language_hints": self._language_hints(),
            },
        }
        response = self.http_client.post_json(
            self.settings.dashscope_asr_endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            payload=payload,
        )
        task_id = response["output"]["task_id"]
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("missing_task_id")
        return task_id

    def _wait_for_task(self, api_key: str, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.dashscope_asr_max_wait_seconds
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        while True:
            response = self.http_client.post_json(
                f"{self.settings.dashscope_task_endpoint}/{task_id}",
                headers=headers,
            )
            output = response["output"]
            task_status = output.get("task_status")
            if task_status == "SUCCEEDED":
                return output
            if task_status not in {"PENDING", "RUNNING"}:
                raise ValueError(f"task_status_{task_status}")
            if time.monotonic() >= deadline:
                raise TimeoutError("asr_task_timeout")
            self.sleep_func(self.settings.dashscope_asr_poll_interval_seconds)

    def _transcription_url(self, task_output: dict[str, Any]) -> str | None:
        results = task_output.get("results")
        if not isinstance(results, list):
            return None
        for result in results:
            if not isinstance(result, dict):
                continue
            if result.get("subtask_status") == "SUCCEEDED" and result.get("transcription_url"):
                return str(result["transcription_url"])
        return None

    def _transcript_text(self, transcript_data: dict[str, Any]) -> str | None:
        transcripts = transcript_data.get("transcripts")
        if not isinstance(transcripts, list):
            return None

        parts = []
        for transcript in transcripts:
            if not isinstance(transcript, dict):
                continue
            text = transcript.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
                continue
            sentences = transcript.get("sentences")
            if isinstance(sentences, list):
                parts.extend(
                    sentence["text"].strip()
                    for sentence in sentences
                    if isinstance(sentence, dict)
                    and isinstance(sentence.get("text"), str)
                    and sentence["text"].strip()
                )
        return " ".join(parts).strip() or None

    def _media_url(self, media: MediaInput) -> str | None:
        for value in (media.object_key, media.client_local_ref):
            if isinstance(value, str) and value.startswith(("http://", "https://", "oss://")):
                return value
        return None

    def _language_hints(self) -> list[str]:
        return [
            item.strip()
            for item in self.settings.dashscope_asr_language_hints.split(",")
            if item.strip()
        ]

    def _warning_result(
        self,
        media: MediaInput,
        reason: str,
        task_id: str | None = None,
        error: str | None = None,
    ) -> SpeechToTextResult:
        warning = {
            "field": "audio",
            "reason": reason,
            "file_id": media.file_id,
        }
        if task_id:
            warning["task_id"] = task_id
        if error:
            warning["error"] = error
        return SpeechToTextResult(
            transcript=None,
            provider=self.provider_name,
            warnings=[warning],
        )


class MockImageUnderstandingProvider:
    provider_name = "mock"

    def describe(self, media: MediaInput) -> ImageUnderstandingResult:
        return ImageUnderstandingResult(
            description=None,
            provider=self.provider_name,
            warnings=[
                {
                    "field": "image",
                    "reason": "vision_provider_mock_no_description",
                    "file_id": media.file_id,
                }
            ],
        )


VISION_SYSTEM_PROMPT = (
    "你是一名图像识别助手，专门识别中餐和日常饮食照片中的食物。"
    "你只输出一个 JSON 对象，不要 Markdown，不要解释。"
    "JSON schema:\n"
    "{\n"
    '  "items": [\n'
    "    {\n"
    '      "name": "string",\n'
    '      "portion_hint": "string",\n'
    '      "estimated_grams": number|null,\n'
    '      "estimated_grams_range": [number, number]|null,\n'
    '      "confidence": 0.0\n'
    "    }\n"
    "  ],\n"
    '  "scene_summary": "string",\n'
    '  "warnings": ["string"]\n'
    "}\n"
    "规则：\n"
    "- 只识别图中真实可见的食物，不要凭空补全。\n"
    "- portion_hint 用自然语言（如 \"约一中份\"、\"占盘子 2/3\"），结合参照物（碗/盘/筷子/手）描述。\n"
    "- estimated_grams 和 estimated_grams_range 是整数克；若无足够信息可填 null。\n"
    "- confidence 表示该 item 的整体识别+份量置信度。\n"
    "- 不能识别食物或图片明显不含食物时，items 留空，并在 warnings 说明原因。\n"
)


class DashScopeVisionUnderstandingProvider:
    provider_name = "dashscope_vision"

    def __init__(
        self,
        settings: Settings,
        client: OpenAI | None = None,
    ) -> None:
        self.settings = settings
        api_key = settings.dashscope_api_key or settings.bailian_api_key
        if not api_key:
            self._client: OpenAI | None = None
            self._missing_key = True
            return
        self._missing_key = False
        self._client = client or OpenAI(
            api_key=api_key,
            base_url=settings.bailian_base_url,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    def describe(self, media: MediaInput) -> ImageUnderstandingResult:
        if self._missing_key:
            return self._warning_result(media, "vision_api_key_missing")

        image_url = self._media_url(media)
        if not image_url:
            return self._warning_result(media, "vision_requires_public_or_oss_url")

        try:
            completion = self._client.chat.completions.create(  # type: ignore[union-attr]
                model=self.settings.vision_model,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {
                                "type": "text",
                                "text": "请按 JSON schema 输出结构化食物识别结果。",
                            },
                        ],
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=self.settings.vision_max_tokens,
            )
        except OpenAIError as exc:
            return self._warning_result(
                media,
                "vision_provider_error",
                error=f"{exc.__class__.__name__}: {exc}",
            )

        content = completion.choices[0].message.content if completion.choices else None
        if not isinstance(content, str) or not content.strip():
            return self._warning_result(media, "vision_empty_response")

        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("json_root_not_object")
        except (json.JSONDecodeError, ValueError) as exc:
            return self._warning_result(
                media,
                "vision_invalid_json",
                error=f"{exc.__class__.__name__}: {exc}",
            )

        description = self._format_description(parsed)
        confidence = self._aggregate_confidence(parsed)
        warnings = self._extract_warnings(parsed, media.file_id)

        if not description:
            return self._warning_result(media, "vision_no_food_items")

        return ImageUnderstandingResult(
            description=description,
            confidence=confidence,
            provider=self.provider_name,
            warnings=warnings,
        )

    def _media_url(self, media: MediaInput) -> str | None:
        for value in (media.object_key, media.client_local_ref):
            if isinstance(value, str) and value.startswith(("http://", "https://", "oss://")):
                return value
        return None

    def _format_description(self, parsed: dict[str, Any]) -> str | None:
        items = parsed.get("items")
        if not isinstance(items, list) or not items:
            return None

        parts: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            portion = str(item.get("portion_hint") or "").strip()
            grams = item.get("estimated_grams")
            grams_range = item.get("estimated_grams_range")
            confidence = item.get("confidence")

            segments = [name]
            if portion:
                segments.append(portion)
            if isinstance(grams, (int, float)):
                if (
                    isinstance(grams_range, list)
                    and len(grams_range) == 2
                    and all(isinstance(v, (int, float)) for v in grams_range)
                ):
                    segments.append(f"约 {int(grams)}g（区间 {int(grams_range[0])}-{int(grams_range[1])}g）")
                else:
                    segments.append(f"约 {int(grams)}g")
            if isinstance(confidence, (int, float)):
                segments.append(f"置信度 {round(float(confidence) * 100)}%")
            parts.append("、".join(segments))

        if not parts:
            return None

        scene = str(parsed.get("scene_summary") or "").strip()
        prefix = f"场景：{scene}。" if scene else ""
        return f"{prefix}识别食物：{'；'.join(parts)}。份量为视觉估算，请用户在确认卡上调整。"

    def _aggregate_confidence(self, parsed: dict[str, Any]) -> float | None:
        items = parsed.get("items")
        if not isinstance(items, list):
            return None
        confidences = [
            float(item["confidence"])
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("confidence"), (int, float))
        ]
        if not confidences:
            return None
        return round(sum(confidences) / len(confidences), 3)

    def _extract_warnings(
        self, parsed: dict[str, Any], file_id: str
    ) -> list[dict[str, Any]]:
        raw_warnings = parsed.get("warnings")
        if not isinstance(raw_warnings, list):
            return []
        return [
            {
                "field": "image",
                "reason": "vision_model_warning",
                "file_id": file_id,
                "detail": str(item),
            }
            for item in raw_warnings
            if isinstance(item, str) and item.strip()
        ]

    def _warning_result(
        self,
        media: MediaInput,
        reason: str,
        error: str | None = None,
    ) -> ImageUnderstandingResult:
        warning: dict[str, Any] = {
            "field": "image",
            "reason": reason,
            "file_id": media.file_id,
        }
        if error:
            warning["error"] = error
        return ImageUnderstandingResult(
            description=None,
            provider=self.provider_name,
            warnings=[warning],
        )


class InputNormalizer:
    def __init__(
        self,
        settings: Settings | None = None,
        speech_provider: SpeechToTextProvider | None = None,
        image_provider: ImageUnderstandingProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.speech_provider = speech_provider or get_speech_to_text_provider(self.settings)
        self.image_provider = image_provider or get_image_understanding_provider(self.settings)

    def normalize(
        self,
        content: list[MessageContentItem],
        files_by_id: dict[str, UploadFile],
    ) -> NormalizedInput:
        normalized_content = list(content)
        normalized_media = []
        prefetched_asr_transcript = self._prefetched_asr_transcript(content)

        for item in content:
            if item.type == "text":
                continue
            if not item.file_id:
                continue
            file = files_by_id.get(item.file_id)
            if not file:
                continue

            media = self._media_input(item, file)
            if item.type == "audio":
                result = (
                    SpeechToTextResult(
                        transcript=prefetched_asr_transcript,
                        provider="client_prefetched_asr",
                    )
                    if prefetched_asr_transcript
                    else self.speech_provider.transcribe(media)
                )
                normalized_media.append(self._audio_context(media, result))
                if result.transcript and not prefetched_asr_transcript:
                    normalized_content.append(
                        MessageContentItem(
                            type="text",
                            text=f"语音转写: {result.transcript}",
                            source="asr",
                        )
                    )
            elif item.type == "image":
                result = self.image_provider.describe(media)
                normalized_media.append(self._image_context(media, result))
                if result.description:
                    normalized_content.append(
                        MessageContentItem(
                            type="text",
                            text=f"图片理解: {result.description}",
                            source="vision",
                        )
                    )

        return NormalizedInput(
            content=normalized_content,
            context={
                "asr_provider": self.speech_provider.provider_name,
                "vision_provider": self.image_provider.provider_name,
                "media": normalized_media,
            },
        )

    def _prefetched_asr_transcript(self, content: list[MessageContentItem]) -> str | None:
        for item in content:
            if item.type != "text" or item.source != "asr" or not item.text:
                continue
            transcript = item.text.strip()
            for prefix in ("语音转写:", "语音转写："):
                if transcript.startswith(prefix):
                    transcript = transcript[len(prefix) :].strip()
                    break
            if transcript:
                return transcript
        return None

    def _media_input(self, item: MessageContentItem, file: UploadFile) -> MediaInput:
        return MediaInput(
            file_id=file.id,
            type=item.type,
            mime_type=file.mime_type,
            storage_provider=file.storage_provider,
            client_local_ref=file.client_local_ref,
            bucket=file.bucket,
            object_key=file.object_key,
            source=item.source or file.source,
            duration_seconds=item.duration_seconds,
        )

    def _audio_context(self, media: MediaInput, result: SpeechToTextResult) -> dict[str, Any]:
        return {
            **self._media_context(media),
            "status": "transcribed" if result.transcript else "unprocessed",
            "transcript": result.transcript,
            "language": result.language,
            "confidence": result.confidence,
            "provider": result.provider,
            "warnings": result.warnings,
        }

    def _image_context(
        self,
        media: MediaInput,
        result: ImageUnderstandingResult,
    ) -> dict[str, Any]:
        return {
            **self._media_context(media),
            "status": "described" if result.description else "unprocessed",
            "description": result.description,
            "confidence": result.confidence,
            "provider": result.provider,
            "warnings": result.warnings,
        }

    def _media_context(self, media: MediaInput) -> dict[str, Any]:
        return {
            "file_id": media.file_id,
            "type": media.type,
            "mime_type": media.mime_type,
            "storage_provider": media.storage_provider,
            "source": media.source,
            "duration_seconds": media.duration_seconds,
            "server_accessible": media.storage_provider != "client_local",
        }


def get_speech_to_text_provider(settings: Settings | None = None) -> SpeechToTextProvider:
    settings = settings or get_settings()
    provider = settings.asr_provider.lower()
    if provider == "mock":
        return MockSpeechToTextProvider()
    if provider in {"dashscope", "dashscope_recording", "bailian", "paraformer"}:
        return DashScopeRecordingSpeechToTextProvider(settings)
    raise AppError(
        "INTERNAL_ERROR",
        "ASR 服务配置不正确",
        status_code=500,
        details={"asr_provider": settings.asr_provider},
    )


def get_image_understanding_provider(
    settings: Settings | None = None,
) -> ImageUnderstandingProvider:
    settings = settings or get_settings()
    provider = settings.vision_provider.lower()
    if provider == "mock":
        return MockImageUnderstandingProvider()
    if provider in {"dashscope", "dashscope_vision", "bailian", "qwen", "qwen_vl"}:
        return DashScopeVisionUnderstandingProvider(settings)
    raise AppError(
        "INTERNAL_ERROR",
        "图片理解服务配置不正确",
        status_code=500,
        details={"vision_provider": settings.vision_provider},
    )
