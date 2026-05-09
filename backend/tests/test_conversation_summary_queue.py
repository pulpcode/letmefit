from datetime import datetime

from app.core.config import Settings
from app.models import ConversationMessage, ConversationSummary
from app.services.conversation_context import LOCAL_SUMMARY_MODEL_NAME, ConversationSummaryService


class FakeDb:
    def __init__(self, rowcount: int = 1, scalar_value=None) -> None:
        self.added = []
        self.flush_count = 0
        self.commit_count = 0
        self.executed = []
        self.rowcount = rowcount
        self.scalar_value = scalar_value

    def add(self, value) -> None:
        self.added.append(value)

    def execute(self, statement):
        self.executed.append(statement)
        return FakeResult(self.rowcount)

    def scalar(self, statement):
        self.executed.append(statement)
        return self.scalar_value

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


def _message(message_id: str) -> ConversationMessage:
    return ConversationMessage(
        id=message_id,
        conversation_id="conv_test",
        user_id="user_test",
        role="user",
        content_json=[{"type": "text", "text": message_id}],
        intent=None,
        requires_review=False,
        created_at=datetime(2026, 5, 5, 12, 0, 0),
    )


def _job() -> ConversationSummary:
    return ConversationSummary(
        id="conv_sum_job",
        conversation_id="conv_test",
        user_id="user_test",
        from_message_id="msg_0",
        to_message_id="msg_1",
        summary_type="rolling",
        status="pending",
        summary_text="",
        summary_json=None,
        token_estimate=None,
        model_name=None,
        created_at=datetime(2026, 5, 5, 12, 1, 0),
        updated_at=datetime(2026, 5, 5, 12, 1, 0),
    )


def test_enqueue_summary_job_without_generating_summary_text(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            conversation_summary_trigger_tokens=3,
            conversation_summary_keep_tokens=2,
        ),
    )
    messages = [_message(f"msg_{index}") for index in range(5)]

    monkeypatch.setattr(service.context_builder, "latest_summary", lambda *_: None)
    monkeypatch.setattr(service.context_builder, "_conversation_messages", lambda *_: messages)
    monkeypatch.setattr(
        service.context_builder,
        "_messages_after_summary",
        lambda current_messages, _: current_messages,
    )
    monkeypatch.setattr(service, "_active_summary_job", lambda *_: None)

    job = service.enqueue_if_needed("user_test", "conv_test")

    assert job is not None
    assert job.status == "pending"
    assert job.summary_type == "rolling"
    assert job.summary_text == ""
    assert job.from_message_id == "msg_0"
    assert job.to_message_id == "msg_2"
    assert db.added == [job]
    assert db.flush_count == 1


def test_process_summary_job_marks_succeeded(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    job = _job()
    messages = [_message("msg_0"), _message("msg_1")]

    monkeypatch.setattr(service, "_previous_succeeded_summary", lambda _: None)
    monkeypatch.setattr(service, "_messages_for_summary_job", lambda _: messages)
    monkeypatch.setattr(service, "_llm_summarize", lambda *_, **__: None)

    assert service.process_job(job) is True

    assert job.status == "succeeded"
    assert "正式事实以档案和记录表为准" in job.summary_text
    assert "用户: msg_0" in job.summary_text
    assert job.summary_json["message_count"] == 2
    assert job.model_name == "local_compose_summary_v1"
    assert job.token_estimate is not None
    assert db.flush_count == 2


def test_process_summary_job_marks_failed_when_messages_missing(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    job = _job()

    monkeypatch.setattr(service, "_previous_succeeded_summary", lambda _: None)
    monkeypatch.setattr(service, "_messages_for_summary_job", lambda _: [])

    assert service.process_job(job) is False

    assert job.status == "failed"
    assert job.summary_json == {"error": "summary_job_messages_not_found"}
    assert db.flush_count == 2


def test_process_pending_jobs_commits_each_processed_job(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    jobs = [_job(), _job()]
    jobs[1].id = "conv_sum_job_2"

    monkeypatch.setattr(service, "recover_stale_running_jobs", lambda: 0)
    monkeypatch.setattr(service, "pending_job_ids", lambda limit: [job.id for job in jobs])
    monkeypatch.setattr(
        service,
        "claim_pending_job",
        lambda job_id: next(job for job in jobs if job.id == job_id),
    )
    monkeypatch.setattr(service, "process_job", lambda job: job.id == "conv_sum_job")

    stats = service.process_pending_jobs(limit=2)

    assert stats == {
        "processed": 2,
        "claimed": 2,
        "succeeded": 1,
        "failed": 1,
        "recovered": 0,
    }
    assert db.commit_count == 4


def test_claim_pending_job_uses_atomic_status_update() -> None:
    job = _job()
    db = FakeDb(rowcount=1, scalar_value=job)
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    claimed = service.claim_pending_job(job.id)

    assert claimed == job
    assert db.flush_count == 1
    assert len(db.executed) == 2


def test_claim_pending_job_returns_none_when_already_claimed() -> None:
    db = FakeDb(rowcount=0, scalar_value=_job())
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    assert service.claim_pending_job("conv_sum_job") is None
    assert db.flush_count == 1
    assert len(db.executed) == 1


def test_recover_stale_running_jobs_updates_timed_out_jobs() -> None:
    db = FakeDb(rowcount=3)
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    recovered = service.recover_stale_running_jobs()

    assert recovered == 3
    assert db.flush_count == 1
    assert len(db.executed) == 1


def test_process_pending_jobs_commits_stale_recovery(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )

    monkeypatch.setattr(service, "recover_stale_running_jobs", lambda: 2)
    monkeypatch.setattr(service, "pending_job_ids", lambda limit: [])

    stats = service.process_pending_jobs(limit=2)

    assert stats["recovered"] == 2
    assert db.commit_count == 1


def test_enqueue_uses_incremental_from_message_id_after_previous_summary(monkeypatch) -> None:
    # Fix: when a previous summary exists, from_message_id should be the first NEW message
    # (after the previous summary's to_message_id), not the previous summary's from_message_id.
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(
            jwt_secret_key="test-secret-key-with-enough-length",
            conversation_summary_trigger_tokens=2,
            conversation_summary_keep_tokens=2,
        ),
    )
    # Messages 0-4 exist; previous summary covers msg_0..msg_1
    previous_summary = ConversationSummary(
        id="conv_sum_prev",
        conversation_id="conv_test",
        user_id="user_test",
        from_message_id="msg_0",
        to_message_id="msg_1",
        summary_type="rolling",
        status="succeeded",
        summary_text="previous summary text",
        summary_json=None,
        token_estimate=None,
        model_name=None,
        created_at=datetime(2026, 5, 5, 12, 0, 0),
        updated_at=datetime(2026, 5, 5, 12, 0, 0),
    )
    all_messages = [_message(f"msg_{i}") for i in range(5)]
    # messages_after_summary = msg_2, msg_3, msg_4 (after previous summary's to_message_id)
    messages_after = all_messages[2:]

    monkeypatch.setattr(service.context_builder, "latest_summary", lambda *_: previous_summary)
    monkeypatch.setattr(service.context_builder, "_conversation_messages", lambda *_: all_messages)
    monkeypatch.setattr(
        service.context_builder,
        "_messages_after_summary",
        lambda current_messages, _: messages_after,
    )
    monkeypatch.setattr(service, "_active_summary_job", lambda *_: None)

    job = service.enqueue_if_needed("user_test", "conv_test")

    assert job is not None
    # from_message_id must be msg_2 (first new message), not msg_0 (previous summary's from)
    assert job.from_message_id == "msg_2"
    assert job.to_message_id == "msg_2"


def test_compose_summary_preserves_new_messages_when_previous_summary_is_long() -> None:
    # Fix: when previous summary is long, new messages must be preserved (not truncated).
    # Old behaviour kept first max_chars bytes, which dropped new messages entirely.
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    long_prev = "x" * 1800
    msg = ConversationMessage(
        id="msg_new",
        conversation_id="conv_test",
        user_id="user_test",
        role="user",
        content_json=[{"type": "text", "text": "新消息内容"}],
        intent=None,
        requires_review=False,
        created_at=datetime(2026, 5, 5, 13, 0, 0),
    )

    result = service.compose_summary(
        previous_summary_text=long_prev,
        messages=[msg],
        max_chars=2000,
    )

    assert "新消息内容" in result
    assert len(result) <= 2000


def test_compose_summary_keeps_tail_of_previous_summary() -> None:
    # The tail (most recent part) of the previous summary should be preserved.
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    prev = "OLD_CONTENT_START " + "middle " * 50 + "RECENT_CONTENT_END"
    msg = ConversationMessage(
        id="msg_x",
        conversation_id="conv_test",
        user_id="user_test",
        role="user",
        content_json=[{"type": "text", "text": "新"}],
        intent=None,
        requires_review=False,
        created_at=datetime(2026, 5, 5, 13, 0, 0),
    )

    result = service.compose_summary(
        previous_summary_text=prev,
        messages=[msg],
        max_chars=300,
    )

    assert "RECENT_CONTENT_END" in result
    assert len(result) <= 300


def test_process_job_uses_llm_when_available(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    job = _job()
    messages = [_message("msg_0"), _message("msg_1")]

    monkeypatch.setattr(service, "_previous_succeeded_summary", lambda _: None)
    monkeypatch.setattr(service, "_messages_for_summary_job", lambda _: messages)
    monkeypatch.setattr(service, "_llm_summarize", lambda *_, **__: "LLM生成的摘要内容")

    assert service.process_job(job) is True

    assert "正式事实以档案和记录表为准" in job.summary_text
    assert "LLM生成的摘要内容" in job.summary_text
    assert job.model_name == service.settings.summary_llm_model
    assert job.summary_json["method"] == service.settings.summary_llm_model
    assert job.token_estimate is not None


def test_process_job_falls_back_to_rule_when_llm_returns_none(monkeypatch) -> None:
    db = FakeDb()
    service = ConversationSummaryService(
        db=db,
        settings=Settings(jwt_secret_key="test-secret-key-with-enough-length"),
    )
    job = _job()
    messages = [_message("msg_0"), _message("msg_1")]

    monkeypatch.setattr(service, "_previous_succeeded_summary", lambda _: None)
    monkeypatch.setattr(service, "_messages_for_summary_job", lambda _: messages)
    monkeypatch.setattr(service, "_llm_summarize", lambda *_, **__: None)

    assert service.process_job(job) is True

    assert "正式事实以档案和记录表为准" in job.summary_text
    assert "用户: msg_0" in job.summary_text
    assert job.model_name == LOCAL_SUMMARY_MODEL_NAME
    assert job.summary_json["method"] == LOCAL_SUMMARY_MODEL_NAME
