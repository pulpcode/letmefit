from pathlib import Path
from typing import Annotated

from fastapi import Depends
from fastapi import UploadFile as FastAPIUploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.input_normalizer import (
    MediaInput,
    SpeechToTextProvider,
    get_speech_to_text_provider,
)
from app.auth.security import new_id, utc_now
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.models import UploadFile as UploadFileModel
from app.schemas.upload import RetentionPolicy, UploadCreateRequest, UploadSource

AUDIO_MIME_EXTENSIONS = {
    "audio/aac": "aac",
    "audio/m4a": "m4a",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-m4a": "m4a",
    "audio/x-wav": "wav",
}

IMAGE_MIME_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}


class UploadService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        speech_provider: SpeechToTextProvider | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.speech_provider = speech_provider

    def create_upload(self, user_id: str, payload: UploadCreateRequest) -> dict:
        file = UploadFileModel(
            id=new_id("file"),
            user_id=user_id,
            storage_provider=payload.storage_provider,
            client_local_ref=payload.client_local_ref,
            bucket=payload.bucket,
            object_key=payload.object_key,
            mime_type=payload.mime_type,
            size_bytes=payload.size_bytes,
            source=payload.source,
            retention_policy=payload.retention_policy,
            status=self._initial_status(payload.storage_provider),
            created_at=utc_now(),
        )
        self.db.add(file)
        self.db.commit()
        self.db.refresh(file)
        return {
            "file": self._response(file),
            "upload_url": None,
            "upload_headers": {},
        }

    async def create_local_file_upload(
        self,
        user_id: str,
        upload_file: FastAPIUploadFile,
        source: UploadSource,
        retention_policy: RetentionPolicy,
        mime_type: str | None = None,
    ) -> dict:
        normalized_mime_type = self._normalize_mime_type(mime_type or upload_file.content_type)
        if normalized_mime_type in AUDIO_MIME_EXTENSIONS:
            extension = AUDIO_MIME_EXTENSIONS[normalized_mime_type]
            kind = "audio"
        elif normalized_mime_type in IMAGE_MIME_EXTENSIONS:
            extension = IMAGE_MIME_EXTENSIONS[normalized_mime_type]
            kind = "image"
        else:
            raise AppError(
                "VALIDATION_ERROR",
                "只支持上传音频或图片文件",
                status_code=422,
                details={"mime_type": normalized_mime_type or None},
            )

        content = await upload_file.read(self.settings.media_max_upload_bytes + 1)
        if not content:
            raise AppError("VALIDATION_ERROR", f"{kind} 文件不能为空", status_code=422)
        if len(content) > self.settings.media_max_upload_bytes:
            raise AppError(
                "VALIDATION_ERROR",
                f"{kind} 文件超过大小限制",
                status_code=422,
                details={"max_bytes": self.settings.media_max_upload_bytes},
            )

        file_id = new_id("file")
        safe_user_id = self._safe_path_segment(user_id)
        relative_path = f"{safe_user_id}/{file_id}.{extension}"
        target_path = Path(self.settings.media_upload_dir) / safe_user_id / f"{file_id}.{extension}"
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
        except OSError as exc:
            raise AppError(
                "INTERNAL_ERROR", f"保存 {kind} 文件失败", status_code=500
            ) from exc

        file = UploadFileModel(
            id=file_id,
            user_id=user_id,
            storage_provider="local_server",
            client_local_ref=None,
            bucket=None,
            object_key=self._public_media_url(relative_path),
            mime_type=normalized_mime_type,
            size_bytes=len(content),
            source=source,
            retention_policy=retention_policy,
            status="ready",
            created_at=utc_now(),
        )
        self.db.add(file)
        self.db.commit()
        self.db.refresh(file)
        return {
            "file": self._response(file),
            "upload_url": None,
            "upload_headers": {},
        }

    def get_upload(self, user_id: str, file_id: str) -> dict:
        return {"file": self._response(self._get_owned_file(user_id, file_id))}

    def transcribe_upload(self, user_id: str, file_id: str) -> dict:
        file = self._get_owned_file(user_id, file_id)
        mime_type = self._normalize_mime_type(file.mime_type)
        if not mime_type.startswith("audio/"):
            raise AppError(
                "VALIDATION_ERROR",
                "只支持转写音频文件",
                status_code=422,
                details={"mime_type": file.mime_type},
            )

        media = MediaInput(
            file_id=file.id,
            type="audio",
            mime_type=mime_type,
            storage_provider=file.storage_provider,
            client_local_ref=file.client_local_ref,
            bucket=file.bucket,
            object_key=file.object_key,
            source=file.source or "microphone",
        )
        speech_provider = self.speech_provider or get_speech_to_text_provider(self.settings)
        result = speech_provider.transcribe(media)
        return {
            "file_id": file.id,
            "status": "transcribed" if result.transcript else "unprocessed",
            "transcript": result.transcript,
            "language": result.language,
            "confidence": result.confidence,
            "provider": result.provider,
            "warnings": result.warnings,
        }

    def delete_upload(self, user_id: str, file_id: str) -> dict:
        file = self._get_owned_file(user_id, file_id)
        file.status = "deleted"
        file.deleted_at = utc_now()
        self.db.commit()
        return {"success": True}

    def _get_owned_file(self, user_id: str, file_id: str) -> UploadFileModel:
        file = self.db.scalar(
            select(UploadFileModel).where(
                UploadFileModel.id == file_id,
                UploadFileModel.user_id == user_id,
                UploadFileModel.deleted_at.is_(None),
                UploadFileModel.status != "deleted",
            )
        )
        if not file:
            raise AppError("RESOURCE_NOT_FOUND", "文件不存在", status_code=404)
        return file

    def _initial_status(self, storage_provider: str) -> str:
        if storage_provider == "client_local":
            return "local_only"
        if storage_provider == "local_server":
            return "ready"
        return "pending"

    def _response(self, file: UploadFileModel) -> dict:
        return {
            "id": file.id,
            "storage_provider": file.storage_provider,
            "client_local_ref": file.client_local_ref,
            "bucket": file.bucket,
            "object_key": file.object_key,
            "mime_type": file.mime_type,
            "size_bytes": file.size_bytes,
            "source": file.source,
            "retention_policy": file.retention_policy,
            "status": file.status,
            "created_at": file.created_at,
            "deleted_at": file.deleted_at,
        }

    def _normalize_mime_type(self, mime_type: str | None) -> str:
        return (mime_type or "").split(";")[0].strip().lower()

    def _public_media_url(self, relative_path: str) -> str:
        return f"{self.settings.media_public_base_url.rstrip('/')}/media/{relative_path}"

    def _safe_path_segment(self, value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def get_upload_service(db: Annotated[Session, Depends(get_db)]) -> UploadService:
    return UploadService(db)
