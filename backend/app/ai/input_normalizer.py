import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import URLError
from urllib.request import Request, urlopen

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
    raise AppError(
        "INTERNAL_ERROR",
        "图片理解服务配置不正确",
        status_code=500,
        details={"vision_provider": settings.vision_provider},
    )
