from __future__ import annotations

import argparse
import csv
import mimetypes
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.ai.input_normalizer import (
    DashScopeRecordingSpeechToTextProvider,
    MediaInput,
    SpeechToTextResult,
)
from app.core.config import get_settings


def main() -> int:
    args = parse_args()
    rows = read_rows(args.csv_path)
    if not rows:
        print(f"No rows found in {args.csv_path}", file=sys.stderr)
        return 2

    settings = get_settings()
    api_key_present = bool(settings.dashscope_api_key or settings.bailian_api_key)
    if not api_key_present:
        print(
            "DASHSCOPE_API_KEY or BAILIAN_API_KEY is required for real ASR smoke test.",
            file=sys.stderr,
        )
        return 2

    provider = DashScopeRecordingSpeechToTextProvider(settings)
    failed = 0

    for index, row in enumerate(rows, start=1):
        label = row.get("object") or f"row-{index}"
        url = row.get("url") or ""
        print(f"object: {label}")

        if not url.startswith(("http://", "https://", "oss://")):
            failed += 1
            print("status: skipped")
            print("reason: url_must_be_http_https_or_oss")
            continue

        result = provider.transcribe(
            MediaInput(
                file_id=f"smoke_{index}",
                type="audio",
                mime_type=guess_mime_type(label, url),
                storage_provider="oss",
                client_local_ref=None,
                bucket=None,
                object_key=url,
                source="microphone",
                duration_seconds=None,
            )
        )

        if result.transcript:
            print("status: transcribed")
            print(f"provider: {result.provider}")
            print(f"transcript: {result.transcript}")
        else:
            failed += 1
            print("status: failed")
            print(f"provider: {result.provider}")
            print_warnings(result)

    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a first-stage DashScope ASR smoke test from an OSS URL CSV."
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        default="../sounds/export_urls.csv",
        help="CSV with columns: object,url. Defaults to ../sounds/export_urls.csv",
    )
    return parser.parse_args()


def read_rows(csv_path: str) -> list[dict[str, str]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [
            {"object": row.get("object", "").strip(), "url": row.get("url", "").strip()}
            for row in csv.DictReader(file)
        ]


def guess_mime_type(label: str, url: str) -> str:
    parsed_path = unquote(urlparse(url).path)
    mime_type, _encoding = mimetypes.guess_type(parsed_path or label)
    return mime_type or "audio/mp4"


def print_warnings(result: SpeechToTextResult) -> None:
    if not result.warnings:
        print("warning: no_transcript_without_warning")
        return
    for warning in result.warnings:
        reason = warning.get("reason", "unknown")
        error = warning.get("error")
        task_id = warning.get("task_id")
        suffix = []
        if task_id:
            suffix.append(f"task_id={task_id}")
        if error:
            suffix.append(f"error={error}")
        extra = f" ({', '.join(suffix)})" if suffix else ""
        print(f"warning: {reason}{extra}")


if __name__ == "__main__":
    raise SystemExit(main())

