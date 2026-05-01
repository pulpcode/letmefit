from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import new_id, utc_now
from app.core.database import get_db
from app.core.errors import AppError
from app.models import UploadFile
from app.schemas.upload import UploadCreateRequest


class UploadService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_upload(self, user_id: str, payload: UploadCreateRequest) -> dict:
        file = UploadFile(
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

    def get_upload(self, user_id: str, file_id: str) -> dict:
        return {"file": self._response(self._get_owned_file(user_id, file_id))}

    def delete_upload(self, user_id: str, file_id: str) -> dict:
        file = self._get_owned_file(user_id, file_id)
        file.status = "deleted"
        file.deleted_at = utc_now()
        self.db.commit()
        return {"success": True}

    def _get_owned_file(self, user_id: str, file_id: str) -> UploadFile:
        file = self.db.scalar(
            select(UploadFile).where(
                UploadFile.id == file_id,
                UploadFile.user_id == user_id,
                UploadFile.deleted_at.is_(None),
                UploadFile.status != "deleted",
            )
        )
        if not file:
            raise AppError("RESOURCE_NOT_FOUND", "文件不存在", status_code=404)
        return file

    def _initial_status(self, storage_provider: str) -> str:
        if storage_provider == "client_local":
            return "local_only"
        return "pending"

    def _response(self, file: UploadFile) -> dict:
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


def get_upload_service(db: Annotated[Session, Depends(get_db)]) -> UploadService:
    return UploadService(db)
