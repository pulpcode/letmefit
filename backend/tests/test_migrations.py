from app.models import Base

EXPECTED_TABLES = {
    "agent_extractions",
    "agent_pending_actions",
    "body_metric_records",
    "conversation_messages",
    "conversation_summaries",
    "conversations",
    "daily_archives",
    "daily_summaries",
    "meal_items",
    "meal_records",
    "message_attachments",
    "refresh_sessions",
    "sms_verification_events",
    "upload_files",
    "user_memories",
    "user_profiles",
    "users",
}

PRIVATE_USER_TABLES = {
    "agent_extractions",
    "agent_pending_actions",
    "body_metric_records",
    "conversation_messages",
    "conversation_summaries",
    "conversations",
    "daily_archives",
    "daily_summaries",
    "meal_records",
    "refresh_sessions",
    "upload_files",
    "user_memories",
    "user_profiles",
}


def test_alembic_metadata_imports() -> None:
    assert Base.metadata is not None
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"


def test_v1_metadata_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_private_tables_include_user_id() -> None:
    for table_name in PRIVATE_USER_TABLES:
        assert "user_id" in Base.metadata.tables[table_name].columns


def test_sms_events_do_not_store_verification_codes() -> None:
    columns = set(Base.metadata.tables["sms_verification_events"].columns.keys())

    assert "code" not in columns
    assert "code_hash" not in columns


def test_media_table_supports_client_local_storage() -> None:
    columns = set(Base.metadata.tables["upload_files"].columns.keys())

    assert "storage_provider" in columns
    assert "client_local_ref" in columns
