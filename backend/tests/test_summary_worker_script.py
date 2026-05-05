import scripts.process_conversation_summaries as worker


def test_stop_controller_records_stop_request() -> None:
    controller = worker.StopController()

    controller.request_stop()

    assert controller.is_running is False


def test_interruptible_sleep_stops_without_waiting_full_interval(monkeypatch) -> None:
    controller = worker.StopController()
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        controller.request_stop()

    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    worker.interruptible_sleep(5.0, controller)

    assert sleep_calls == [0.5]


def test_run_loop_is_serial_and_stops_after_current_iteration(monkeypatch) -> None:
    controller = worker.StopController()
    calls = []

    def fake_process_once(limit):
        calls.append(("process", limit))
        controller.request_stop()
        return {"processed": 1, "claimed": 1, "succeeded": 1, "failed": 0, "recovered": 0}

    monkeypatch.setattr(worker, "process_once", fake_process_once)
    monkeypatch.setattr(worker, "print_stats", lambda stats: calls.append(("print", stats)))
    monkeypatch.setattr(
        worker,
        "interruptible_sleep",
        lambda interval, stop_controller: calls.append(("sleep", interval)),
    )

    worker.run_loop(limit=10, interval_seconds=5.0, stop_controller=controller)

    assert calls == [
        ("process", 10),
        ("print", {"processed": 1, "claimed": 1, "succeeded": 1, "failed": 0, "recovered": 0}),
        ("sleep", 5.0),
    ]
