import io

import pytest
from fastapi import UploadFile as FastAPIUploadFile
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.ai.input_normalizer import MediaInput, SpeechToTextResult
from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import UploadFile as UploadFileModel
from app.models import User
from app.schemas.upload import UploadCreateRequest
from app.services.uploads import UploadService, get_upload_service


class FakeUploadService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_upload(self, user_id: str, payload: UploadCreateRequest) -> dict:
        self.calls.append(("create", user_id, payload.storage_provider, payload.client_local_ref))
        return {
            "file": self._file("file_test", payload),
            "upload_url": None,
            "upload_headers": {},
        }

    async def create_local_file_upload(
        self,
        user_id: str,
        upload_file: FastAPIUploadFile,
        source: str,
        retention_policy: str,
        mime_type: str | None = None,
    ) -> dict:
        self.calls.append(("create_local_file", user_id, source, retention_policy, mime_type))
        return {
            "file": {
                "id": "file_audio",
                "storage_provider": "local_server",
                "client_local_ref": None,
                "bucket": None,
                "object_key": "https://www.letmefit.cloud/media/user_test/file_audio.mp3",
                "mime_type": mime_type or upload_file.content_type,
                "size_bytes": 1234,
                "source": source,
                "retention_policy": retention_policy,
                "status": "ready",
                "created_at": "2026-05-01T12:00:00",
                "deleted_at": None,
            },
            "upload_url": None,
            "upload_headers": {},
        }

    def get_upload(self, user_id: str, file_id: str) -> dict:
        self.calls.append(("get", user_id, file_id))
        return {
            "file": {
                "id": file_id,
                "storage_provider": "client_local",
                "client_local_ref": "local://camera/1",
                "bucket": None,
                "object_key": None,
                "mime_type": "image/jpeg",
                "size_bytes": 1234,
                "source": "camera",
                "retention_policy": "transient",
                "status": "local_only",
                "created_at": "2026-05-01T12:00:00",
                "deleted_at": None,
            }
        }

    def transcribe_upload(self, user_id: str, file_id: str) -> dict:
        self.calls.append(("transcribe", user_id, file_id))
        return {
            "file_id": file_id,
            "status": "transcribed",
            "transcript": "你叫什么名字",
            "language": "zh-CN",
            "confidence": None,
            "provider": "fake_asr",
            "warnings": [],
        }

    def delete_upload(self, user_id: str, file_id: str) -> dict:
        self.calls.append(("delete", user_id, file_id))
        return {"success": True}

    def _file(self, file_id: str, payload: UploadCreateRequest) -> dict:
        return {
            "id": file_id,
            "storage_provider": payload.storage_provider,
            "client_local_ref": payload.client_local_ref,
            "bucket": payload.bucket,
            "object_key": payload.object_key,
            "mime_type": payload.mime_type,
            "size_bytes": payload.size_bytes,
            "source": payload.source,
            "retention_policy": payload.retention_policy,
            "status": "local_only",
            "created_at": "2026-05-01T12:00:00",
            "deleted_at": None,
        }


def _authorized_app(service: FakeUploadService | None = None):
    app = create_app()
    if service:
        app.dependency_overrides[get_upload_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: User(
        id="user_test",
        phone_number="+8613800138000",
        country_code="86",
        status="active",
    )
    return app


def test_uploads_require_authentication() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/uploads",
        json={
            "client_local_ref": "local://camera/1",
            "mime_type": "image/jpeg",
            "source": "camera",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_local_file_upload_requires_authentication() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/uploads/local-file",
        files={"file": ("voice.mp3", b"audio-bytes", "audio/mpeg")},
        data={"mime_type": "audio/mpeg"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_create_client_local_upload_uses_current_user() -> None:
    service = FakeUploadService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/uploads",
        json={
            "storage_provider": "client_local",
            "client_local_ref": "local://camera/1",
            "mime_type": "image/jpeg",
            "size_bytes": 1234,
            "source": "camera",
            "retention_policy": "transient",
        },
        headers={"x-request-id": "req_upload"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_upload"
    assert body["data"]["file"]["id"] == "file_test"
    assert body["data"]["file"]["status"] == "local_only"
    assert body["data"]["upload_url"] is None
    assert service.calls[0] == ("create", "user_test", "client_local", "local://camera/1")


def test_create_local_file_upload_uses_current_user() -> None:
    service = FakeUploadService()
    client = TestClient(_authorized_app(service))

    response = client.post(
        "/v1/uploads/local-file",
        files={"file": ("voice.mp3", b"audio-bytes", "audio/mpeg")},
        data={"source": "microphone", "retention_policy": "transient", "mime_type": "audio/mpeg"},
        headers={"x-request-id": "req_audio_upload"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "req_audio_upload"
    assert body["data"]["file"]["id"] == "file_audio"
    assert body["data"]["file"]["storage_provider"] == "local_server"
    assert body["data"]["file"]["status"] == "ready"
    assert body["data"]["file"]["object_key"].startswith("https://www.letmefit.cloud/media/")
    assert service.calls[0] == (
        "create_local_file",
        "user_test",
        "microphone",
        "transient",
        "audio/mpeg",
    )


def test_get_and_delete_upload_use_current_user() -> None:
    service = FakeUploadService()
    client = TestClient(_authorized_app(service))

    get_response = client.get("/v1/uploads/file_test")
    delete_response = client.delete("/v1/uploads/file_test")

    assert get_response.status_code == 200
    assert get_response.json()["data"]["file"]["id"] == "file_test"
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"success": True}
    assert service.calls == [
        ("get", "user_test", "file_test"),
        ("delete", "user_test", "file_test"),
    ]


def test_transcribe_upload_uses_current_user() -> None:
    service = FakeUploadService()
    client = TestClient(_authorized_app(service))

    response = client.post("/v1/uploads/file_audio/transcription")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["file_id"] == "file_audio"
    assert body["status"] == "transcribed"
    assert body["transcript"] == "你叫什么名字"
    assert service.calls == [("transcribe", "user_test", "file_audio")]


def test_client_local_upload_requires_local_ref() -> None:
    client = TestClient(_authorized_app())

    response = client.post(
        "/v1/uploads",
        json={
            "storage_provider": "client_local",
            "mime_type": "image/jpeg",
            "source": "camera",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class FakeDb:
    def __init__(self) -> None:
        self.added = None
        self.committed = False

    def add(self, value) -> None:
        self.added = value

    def commit(self) -> None:
        self.committed = True

    def refresh(self, value) -> None:
        pass


class FakeScalarDb:
    def __init__(self, value) -> None:
        self.value = value

    def scalar(self, statement):
        return self.value


class FakeSpeechProvider:
    provider_name = "fake_asr"

    def transcribe(self, media: MediaInput) -> SpeechToTextResult:
        return SpeechToTextResult(
            transcript="你叫什么名字",
            language="zh-CN",
            provider=self.provider_name,
        )


def _upload_file_model(mime_type: str = "audio/mpeg") -> UploadFileModel:
    return UploadFileModel(
        id="file_audio",
        user_id="user_test",
        storage_provider="local_server",
        client_local_ref=None,
        bucket=None,
        object_key="https://www.letmefit.cloud/media/user_test/file_audio.mp3",
        mime_type=mime_type,
        size_bytes=1234,
        source="microphone",
        retention_policy="transient",
        status="ready",
    )


def test_upload_service_transcribes_owned_audio_upload() -> None:
    service = UploadService(
        db=FakeScalarDb(_upload_file_model()),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
        speech_provider=FakeSpeechProvider(),
    )

    result = service.transcribe_upload("user_test", "file_audio")

    assert result["file_id"] == "file_audio"
    assert result["status"] == "transcribed"
    assert result["transcript"] == "你叫什么名字"
    assert result["provider"] == "fake_asr"


def test_upload_service_transcribe_rejects_non_audio_upload() -> None:
    service = UploadService(
        db=FakeScalarDb(_upload_file_model("image/jpeg")),
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
        speech_provider=FakeSpeechProvider(),
    )

    with pytest.raises(AppError) as exc_info:
        service.transcribe_upload("user_test", "file_image")

    assert exc_info.value.code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_upload_service_saves_local_audio_file(tmp_path) -> None:
    db = FakeDb()
    service = UploadService(
        db=db,
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            media_upload_dir=str(tmp_path),
            media_public_base_url="https://www.letmefit.cloud",
        ),
    )
    upload_file = FastAPIUploadFile(
        file=io.BytesIO(b"audio-bytes"),
        filename="voice.mp3",
        headers=Headers({"content-type": "audio/mpeg"}),
    )

    result = await service.create_local_file_upload(
        "user_test",
        upload_file=upload_file,
        source="microphone",
        retention_policy="transient",
    )

    saved_files = list(tmp_path.rglob("*.mp3"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"audio-bytes"
    assert db.committed is True
    assert db.added.storage_provider == "local_server"
    assert db.added.status == "ready"
    assert result["file"]["object_key"].startswith("https://www.letmefit.cloud/media/user_test/")
    assert result["file"]["mime_type"] == "audio/mpeg"
    assert result["file"]["size_bytes"] == len(b"audio-bytes")


@pytest.mark.asyncio
async def test_upload_service_saves_webm_audio_file(tmp_path) -> None:
    db = FakeDb()
    service = UploadService(
        db=db,
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            media_upload_dir=str(tmp_path),
            media_public_base_url="https://www.letmefit.cloud",
        ),
    )
    upload_file = FastAPIUploadFile(
        file=io.BytesIO(b"\x1a\x45\xdf\xa3webm-audio-bytes"),
        filename="voice.webm",
        headers=Headers({"content-type": "audio/webm"}),
    )

    result = await service.create_local_file_upload(
        "user_test",
        upload_file=upload_file,
        source="microphone",
        retention_policy="transient",
    )

    saved_files = list(tmp_path.rglob("*.webm"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"\x1a\x45\xdf\xa3webm-audio-bytes"
    assert result["file"]["object_key"].endswith(".webm")
    assert result["file"]["mime_type"] == "audio/webm"


@pytest.mark.asyncio
async def test_upload_service_saves_jpeg_image_file(tmp_path) -> None:
    db = FakeDb()
    service = UploadService(
        db=db,
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            media_upload_dir=str(tmp_path),
            media_public_base_url="https://www.letmefit.cloud",
        ),
    )
    upload_file = FastAPIUploadFile(
        file=io.BytesIO(b"\xff\xd8\xff\xe0jpeg-bytes"),
        filename="meal.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )

    result = await service.create_local_file_upload(
        "user_test",
        upload_file=upload_file,
        source="camera",
        retention_policy="transient",
    )

    saved_files = list(tmp_path.rglob("*.jpg"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"\xff\xd8\xff\xe0jpeg-bytes"
    assert db.added.storage_provider == "local_server"
    assert db.added.status == "ready"
    assert db.added.source == "camera"
    assert result["file"]["mime_type"] == "image/jpeg"
    assert result["file"]["object_key"].endswith(".jpg")


@pytest.mark.asyncio
async def test_upload_service_rejects_unsupported_local_file(tmp_path) -> None:
    service = UploadService(
        db=FakeDb(),
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            media_upload_dir=str(tmp_path),
        ),
    )
    upload_file = FastAPIUploadFile(
        file=io.BytesIO(b"not-audio"),
        filename="note.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    with pytest.raises(AppError) as exc_info:
        await service.create_local_file_upload(
            "user_test",
            upload_file=upload_file,
            source="microphone",
            retention_policy="transient",
        )

    assert exc_info.value.code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_upload_service_rejects_oversized_local_audio_file(tmp_path) -> None:
    service = UploadService(
        db=FakeDb(),
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            media_upload_dir=str(tmp_path),
            media_max_upload_bytes=4,
        ),
    )
    upload_file = FastAPIUploadFile(
        file=io.BytesIO(b"audio"),
        filename="voice.mp3",
        headers=Headers({"content-type": "audio/mpeg"}),
    )

    with pytest.raises(AppError) as exc_info:
        await service.create_local_file_upload(
            "user_test",
            upload_file=upload_file,
            source="microphone",
            retention_policy="transient",
        )

    assert exc_info.value.code == "VALIDATION_ERROR"
    assert exc_info.value.details["max_bytes"] == 4
