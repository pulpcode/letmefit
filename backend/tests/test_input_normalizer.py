from app.ai.input_normalizer import (
    DashScopeRecordingSpeechToTextProvider,
    DashScopeVisionUnderstandingProvider,
    ImageUnderstandingResult,
    InputNormalizer,
    JsonHttpClient,
    MediaInput,
    SpeechToTextResult,
    get_image_understanding_provider,
    get_speech_to_text_provider,
)
from app.core.config import Settings
from app.models import UploadFile
from app.schemas.conversation import MessageContentItem


class FakeSpeechProvider:
    provider_name = "fake_asr"

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        return SpeechToTextResult(
            transcript="今天早餐吃了两个鸡蛋",
            language="zh-CN",
            confidence=0.91,
            provider=self.provider_name,
        )


class FailingSpeechProvider:
    provider_name = "failing_asr"

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        raise AssertionError("prefetched ASR should skip provider transcription")


class FakeImageProvider:
    provider_name = "fake_vision"

    def describe(self, media: MediaInput) -> ImageUnderstandingResult:
        return ImageUnderstandingResult(
            description="图片中可能是一份鸡胸肉沙拉，需要用户确认份量。",
            confidence=0.66,
            provider=self.provider_name,
        )


def _file(
    file_id: str,
    mime_type: str,
    storage_provider: str = "client_local",
    object_key: str | None = None,
) -> UploadFile:
    return UploadFile(
        id=file_id,
        user_id="user_test",
        storage_provider=storage_provider,
        client_local_ref=f"local://{file_id}",
        bucket=None,
        object_key=object_key,
        mime_type=mime_type,
        size_bytes=1234,
        source="microphone" if mime_type.startswith("audio/") else "camera",
        retention_policy="transient",
        status="local_only" if storage_provider == "client_local" else "ready",
    )


def _normalizer(
    speech_provider=None,
    image_provider=None,
) -> InputNormalizer:
    return InputNormalizer(
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
        speech_provider=speech_provider,
        image_provider=image_provider,
    )


def test_input_normalizer_adds_asr_transcript_text() -> None:
    normalizer = _normalizer(speech_provider=FakeSpeechProvider())

    result = normalizer.normalize(
        [MessageContentItem(type="audio", file_id="file_audio", duration_seconds=5)],
        {"file_audio": _file("file_audio", "audio/m4a")},
    )

    assert result.content[-1].type == "text"
    assert result.content[-1].source == "asr"
    assert result.content[-1].text == "语音转写: 今天早餐吃了两个鸡蛋"
    media_context = result.context["media"][0]
    assert media_context["status"] == "transcribed"
    assert media_context["server_accessible"] is False


def test_input_normalizer_reuses_prefetched_asr_without_duplicate_transcript() -> None:
    normalizer = _normalizer(speech_provider=FailingSpeechProvider())

    result = normalizer.normalize(
        [
            MessageContentItem(type="audio", file_id="file_audio", duration_seconds=3),
            MessageContentItem(type="text", text="语音转写: 你叫什么名字", source="asr"),
        ],
        {"file_audio": _file("file_audio", "audio/mpeg", storage_provider="local_server")},
    )

    asr_texts = [item for item in result.content if item.type == "text" and item.source == "asr"]
    assert len(asr_texts) == 1
    assert asr_texts[0].text == "语音转写: 你叫什么名字"
    media_context = result.context["media"][0]
    assert media_context["status"] == "transcribed"
    assert media_context["transcript"] == "你叫什么名字"
    assert media_context["provider"] == "client_prefetched_asr"


def test_input_normalizer_adds_image_description_text() -> None:
    normalizer = _normalizer(image_provider=FakeImageProvider())

    result = normalizer.normalize(
        [MessageContentItem(type="image", file_id="file_image", source="camera")],
        {"file_image": _file("file_image", "image/jpeg", storage_provider="local_server")},
    )

    assert result.content[-1].type == "text"
    assert result.content[-1].source == "vision"
    assert "鸡胸肉沙拉" in (result.content[-1].text or "")
    media_context = result.context["media"][0]
    assert media_context["status"] == "described"
    assert media_context["server_accessible"] is True


def test_input_normalizer_mock_provider_records_unprocessed_media() -> None:
    result = _normalizer().normalize(
        [
            MessageContentItem(type="text", text="帮我看看这张图"),
            MessageContentItem(type="image", file_id="file_image", source="camera"),
        ],
        {"file_image": _file("file_image", "image/jpeg")},
    )

    assert len(result.content) == 2
    assert result.context["vision_provider"] == "mock"
    assert result.context["media"][0]["status"] == "unprocessed"
    assert result.context["media"][0]["warnings"][0]["reason"] == (
        "vision_provider_mock_no_description"
    )


class FakeJsonHttpClient(JsonHttpClient):
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict | None = None,
    ) -> dict:
        self.calls.append(("post", url, headers, payload))
        if url.endswith("/transcription"):
            return {"output": {"task_status": "PENDING", "task_id": "task_test"}}
        return {
            "output": {
                "task_id": "task_test",
                "task_status": "SUCCEEDED",
                "results": [
                    {
                        "subtask_status": "SUCCEEDED",
                        "transcription_url": "https://result.example/transcript.json",
                    }
                ],
            }
        }

    def get_json(self, url: str) -> dict:
        self.calls.append(("get", url, {}, None))
        return {"transcripts": [{"text": "今天午餐吃了鸡胸肉"}]}


def test_dashscope_recording_provider_transcribes_public_audio_url() -> None:
    http_client = FakeJsonHttpClient()
    settings = Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        dashscope_api_key="sk-test",
        dashscope_asr_endpoint="https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription",
        dashscope_task_endpoint="https://dashscope.aliyuncs.com/api/v1/tasks",
    )
    provider = DashScopeRecordingSpeechToTextProvider(
        settings=settings,
        http_client=http_client,
        sleep_func=lambda seconds: None,
    )

    result = provider.transcribe(
        MediaInput(
            file_id="file_audio",
            type="audio",
            mime_type="audio/m4a",
            storage_provider="oss",
            client_local_ref=None,
            bucket=None,
            object_key="https://media.example/audio.m4a",
            source="microphone",
            duration_seconds=5,
        )
    )

    assert result.transcript == "今天午餐吃了鸡胸肉"
    assert result.provider == "dashscope_recording"
    submit_call = http_client.calls[0]
    assert submit_call[2]["X-DashScope-Async"] == "enable"
    assert submit_call[3]["model"] == "paraformer-v2"
    assert submit_call[3]["input"]["file_urls"] == ["https://media.example/audio.m4a"]


def test_dashscope_recording_provider_requires_reachable_audio_url() -> None:
    provider = DashScopeRecordingSpeechToTextProvider(
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            dashscope_api_key="sk-test",
        ),
        http_client=FakeJsonHttpClient(),
        sleep_func=lambda seconds: None,
    )

    result = provider.transcribe(
        MediaInput(
            file_id="file_audio",
            type="audio",
            mime_type="audio/m4a",
            storage_provider="client_local",
            client_local_ref="local://audio",
            bucket=None,
            object_key=None,
            source="microphone",
            duration_seconds=5,
        )
    )

    assert result.transcript is None
    assert result.warnings[0]["reason"] == "asr_requires_public_or_oss_url"


def test_get_speech_to_text_provider_supports_dashscope_alias() -> None:
    provider = get_speech_to_text_provider(
        Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            asr_provider="dashscope",
        )
    )

    assert isinstance(provider, DashScopeRecordingSpeechToTextProvider)


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class FakeOpenAIChatCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeCompletion(self.content)


class FakeOpenAIClient:
    def __init__(self, content: str) -> None:
        completions = FakeOpenAIChatCompletions(content)
        self.chat = type("Chat", (), {"completions": completions})()
        self._completions = completions


def _vision_settings() -> Settings:
    return Settings(
        jwt_secret_key="test-secret-key-with-enough-length",
        vision_provider="dashscope",
        vision_model="qwen-vl-max-latest",
        bailian_api_key="sk-test",
    )


def _image_media() -> MediaInput:
    return MediaInput(
        file_id="file_image",
        type="image",
        mime_type="image/jpeg",
        storage_provider="local_server",
        client_local_ref=None,
        bucket=None,
        object_key="https://media.example/meal.jpg",
        source="camera",
        duration_seconds=None,
    )


def test_dashscope_vision_provider_formats_structured_description() -> None:
    fake_client = FakeOpenAIClient(
        content=(
            '{"items":['
            '{"name":"宫保鸡丁","portion_hint":"约一中份","estimated_grams":220,'
            '"estimated_grams_range":[180,260],"confidence":0.85},'
            '{"name":"白米饭","portion_hint":"一小碗","estimated_grams":150,'
            '"confidence":0.9}'
            '],"scene_summary":"家常餐桌俯拍","warnings":[]}'
        )
    )
    provider = DashScopeVisionUnderstandingProvider(
        settings=_vision_settings(),
        client=fake_client,
    )

    result = provider.describe(_image_media())

    assert result.provider == "dashscope_vision"
    assert result.description is not None
    assert "宫保鸡丁" in result.description
    assert "白米饭" in result.description
    assert "220g" in result.description
    assert "180-260g" in result.description
    assert "85%" in result.description
    assert "家常餐桌俯拍" in result.description
    assert result.confidence is not None
    assert 0.85 <= result.confidence <= 0.9
    sent = fake_client._completions.last_kwargs
    assert sent["model"] == "qwen-vl-max-latest"
    assert sent["response_format"] == {"type": "json_object"}
    user_msg = sent["messages"][1]
    assert user_msg["content"][0]["image_url"]["url"].startswith("https://media.example/")


def test_dashscope_vision_provider_warns_on_invalid_json() -> None:
    provider = DashScopeVisionUnderstandingProvider(
        settings=_vision_settings(),
        client=FakeOpenAIClient(content="not-json"),
    )

    result = provider.describe(_image_media())

    assert result.description is None
    assert result.warnings[0]["reason"] == "vision_invalid_json"


def test_dashscope_vision_provider_warns_when_no_food_items() -> None:
    provider = DashScopeVisionUnderstandingProvider(
        settings=_vision_settings(),
        client=FakeOpenAIClient(content='{"items":[],"warnings":["no_food"]}'),
    )

    result = provider.describe(_image_media())

    assert result.description is None
    assert result.warnings[0]["reason"] == "vision_no_food_items"


def test_dashscope_vision_provider_requires_reachable_image_url() -> None:
    provider = DashScopeVisionUnderstandingProvider(
        settings=_vision_settings(),
        client=FakeOpenAIClient(content="{}"),
    )

    media = MediaInput(
        file_id="file_image",
        type="image",
        mime_type="image/jpeg",
        storage_provider="client_local",
        client_local_ref="local://meal",
        bucket=None,
        object_key=None,
        source="camera",
        duration_seconds=None,
    )

    result = provider.describe(media)

    assert result.description is None
    assert result.warnings[0]["reason"] == "vision_requires_public_or_oss_url"


def test_dashscope_vision_provider_warns_when_api_key_missing() -> None:
    provider = DashScopeVisionUnderstandingProvider(
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            vision_provider="dashscope",
            bailian_api_key="",
            dashscope_api_key="",
        ),
    )

    result = provider.describe(_image_media())

    assert result.description is None
    assert result.warnings[0]["reason"] == "vision_api_key_missing"


def test_get_image_understanding_provider_supports_dashscope_alias() -> None:
    provider = get_image_understanding_provider(
        Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            vision_provider="qwen_vl",
            bailian_api_key="sk-test",
        )
    )

    assert isinstance(provider, DashScopeVisionUnderstandingProvider)
