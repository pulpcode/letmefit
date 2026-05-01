from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import create_app
from app.models import User
from app.schemas.upload import UploadCreateRequest
from app.services.uploads import get_upload_service


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
