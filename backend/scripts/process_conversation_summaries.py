from __future__ import annotations

import argparse
import signal
import time

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.conversation_context import ConversationSummaryService


class StopController:
    def __init__(self) -> None:
        self.is_running = True

    def request_stop(self, *_args) -> None:
        print("Received stop signal, finishing current task before exiting...", flush=True)
        self.is_running = False


def main() -> int:
    args = parse_args()
    stop_controller = StopController()
    install_signal_handlers(stop_controller)
    if args.loop:
        run_loop(
            limit=args.limit,
            interval_seconds=args.interval_seconds,
            stop_controller=stop_controller,
        )
        return 0

    stats = process_once(limit=args.limit)
    print_stats(stats)
    return 1 if stats["failed"] else 0


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Process pending conversation summary jobs.")
    parser.add_argument(
        "--limit",
        type=int,
        default=settings.conversation_summary_worker_limit,
        help="Max jobs to process per batch.",
    )
    parser.add_argument("--loop", action="store_true", help="Keep polling for pending jobs.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=settings.conversation_summary_worker_interval_seconds,
        help="Polling interval when --loop is enabled.",
    )
    return parser.parse_args()


def install_signal_handlers(stop_controller: StopController) -> None:
    signal.signal(signal.SIGINT, stop_controller.request_stop)
    signal.signal(signal.SIGTERM, stop_controller.request_stop)


def run_loop(
    limit: int,
    interval_seconds: float,
    stop_controller: StopController | None = None,
) -> None:
    controller = stop_controller or StopController()
    while controller.is_running:
        stats = process_once(limit=limit)
        print_stats(stats)
        interruptible_sleep(max(0.5, interval_seconds), controller)


def interruptible_sleep(interval_seconds: float, stop_controller: StopController) -> None:
    remaining = interval_seconds
    while stop_controller.is_running and remaining > 0:
        sleep_seconds = min(0.5, remaining)
        time.sleep(sleep_seconds)
        remaining -= sleep_seconds


def process_once(limit: int) -> dict[str, int]:
    db = SessionLocal()
    try:
        return ConversationSummaryService(db).process_pending_jobs(limit=limit)
    finally:
        db.close()


def print_stats(stats: dict[str, int]) -> None:
    print(
        "summary_jobs "
        f"processed={stats['processed']} "
        f"claimed={stats.get('claimed', 0)} "
        f"succeeded={stats['succeeded']} "
        f"failed={stats['failed']} "
        f"recovered={stats.get('recovered', 0)}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
