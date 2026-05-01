from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

StorageProvider = Literal["client_local", "local_server", "cos", "oss", "s3"]
UploadSource = Literal["camera", "album", "microphone", "upload"]
RetentionPolicy = Literal["transient", "retained"]


class UploadCreateRequest(BaseModel):
    storage_provider: StorageProvider = "client_local"
    client_local_ref: str | None = Field(default=None, max_length=256)
    bucket: str | None = Field(default=None, max_length=128)
    object_key: str | None = Field(default=None, max_length=512)
    mime_type: str = Field(min_length=1, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    source: UploadSource
    retention_policy: RetentionPolicy = "transient"

    @model_validator(mode="after")
    def validate_storage_fields(self) -> "UploadCreateRequest":
        if self.storage_provider == "client_local" and not self.client_local_ref:
            raise ValueError("client_local storage requires client_local_ref")
        return self


class UploadFileResponse(BaseModel):
    id: str
    storage_provider: str
    client_local_ref: str | None
    bucket: str | None
    object_key: str | None
    mime_type: str
    size_bytes: int | None
    source: str
    retention_policy: str
    status: str
    created_at: datetime
    deleted_at: datetime | None


class UploadCreateResponse(BaseModel):
    file: UploadFileResponse
    upload_url: str | None = None
    upload_headers: dict[str, str] = Field(default_factory=dict)
