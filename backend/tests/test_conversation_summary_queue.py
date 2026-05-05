from datetime import datetime

from app.core.config import Settings
from app.models import ConversationMessage, ConversationSummary
from app.services.conversation_context import ConversationSummaryService


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
            conversation_summary_trigger_messages=3,
            conversation_context_short_term_full_turns=1,
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
