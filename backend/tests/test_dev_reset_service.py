import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services.dev_reset import DevResetService


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class FakeDb:
    def __init__(self) -> None:
        self.statements = []
        self.commit_count = 0
        self.rollback_count = 0

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(len(self.statements))

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _settings(environment: str = "local") -> Settings:
    return Settings(jwt_secret_key="test-secret-key-with-enough-length", environment=environment)


def test_dev_reset_rejects_non_dev_environment() -> None:
    service = DevResetService(db=FakeDb(), settings=_settings("production"))

    with pytest.raises(AppError) as exc_info:
        service.reset_current_user("user_test")
    with pytest.raises(AppError) as full_exc_info:
        service.reset_current_user_full("user_test")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "RESOURCE_NOT_FOUND"
    assert full_exc_info.value.status_code == 404
    assert full_exc_info.value.code == "RESOURCE_NOT_FOUND"


def test_dev_reset_deletes_user_business_tables_in_dependency_order() -> None:
    db = FakeDb()
    service = DevResetService(db=db, settings=_settings())

    response = service.reset_current_user("user_test")

    table_order = [statement.table.name for statement in db.statements]
    assert table_order == [
        "message_attachments",
        "daily_summaries",
        "daily_archives",
        "user_memories",
        "meal_items",
        "meal_records",
        "body_metric_records",
        "agent_pending_actions",
        "agent_extractions",
        "conversation_summaries",
        "conversation_messages",
        "conversations",
        "upload_files",
    ]
    assert response["deleted"]["message_attachments"] == 1
    assert response["deleted"]["upload_files"] == 13
    assert response["preserved"] == [
        "users",
        "refresh_sessions",
        "sms_verification_events",
        "user_profiles",
    ]
    assert db.commit_count == 1
    assert db.rollback_count == 0


def test_dev_reset_full_also_deletes_profile() -> None:
    db = FakeDb()
    service = DevResetService(db=db, settings=_settings())

    response = service.reset_current_user_full("user_test")

    table_order = [statement.table.name for statement in db.statements]
    assert table_order == [
        "message_attachments",
        "daily_summaries",
        "daily_archives",
        "user_memories",
        "meal_items",
        "meal_records",
        "body_metric_records",
        "agent_pending_actions",
        "agent_extractions",
        "conversation_summaries",
        "conversation_messages",
        "conversations",
        "upload_files",
        "user_profiles",
    ]
    assert response["deleted"]["user_profiles"] == 14
    assert response["preserved"] == [
        "users",
        "refresh_sessions",
        "sms_verification_events",
    ]
    assert db.commit_count == 1
    assert db.rollback_count == 0
