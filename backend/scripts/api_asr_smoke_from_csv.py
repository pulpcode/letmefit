from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    rows = read_rows(args.csv_path)
    if not rows:
        print(f"No rows found in {args.csv_path}", file=sys.stderr)
        return 2

    try:
        access_token = args.access_token or os.getenv("LETMEFIT_ACCESS_TOKEN") or login(
            base_url=base_url,
            phone=args.phone,
            code=args.sms_code,
            timeout_seconds=args.timeout_seconds,
        )
        conversation_id = create_conversation(
            base_url=base_url,
            access_token=access_token,
            timeout_seconds=args.timeout_seconds,
        )

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

            file_id = create_oss_upload(
                base_url=base_url,
                access_token=access_token,
                label=label,
                url=url,
                timeout_seconds=args.timeout_seconds,
            )
            result = send_audio_message(
                base_url=base_url,
                access_token=access_token,
                conversation_id=conversation_id,
                file_id=file_id,
                timeout_seconds=args.timeout_seconds,
            )
            print_api_result(result)
            if not result.get("requires_review"):
                failed += 1

        return 1 if failed else 0
    except SmokeError as exc:
        print(f"smoke_error: {exc}", file=sys.stderr)
        return 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a server API ASR smoke test from OSS URLs. "
            "The server creates upload records and sends audio messages."
        )
    )
    parser.add_argument("csv_path", help="CSV with columns: object,url")
    parser.add_argument(
        "--base-url",
        default=os.getenv("LETMEFIT_API_BASE_URL", "http://127.0.0.1:8000/v1"),
        help="API base URL, e.g. https://www.letmefit.cloud/v1",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help="Existing JWT access token. If omitted, the script uses SMS verify.",
    )
    parser.add_argument(
        "--phone",
        default=os.getenv("LETMEFIT_TEST_PHONE", "+8613800000000"),
        help="Phone number for mock SMS login.",
    )
    parser.add_argument(
        "--sms-code",
        default=os.getenv("LETMEFIT_TEST_SMS_CODE", "123456"),
        help="SMS code for mock SMS login.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser.parse_args()


def read_rows(csv_path: str) -> list[dict[str, str]]:
    path = Path(csv_path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return [
            {"object": row.get("object", "").strip(), "url": row.get("url", "").strip()}
            for row in csv.DictReader(file)
        ]


def login(base_url: str, phone: str, code: str, timeout_seconds: int) -> str:
    response = request_json(
        "POST",
        f"{base_url}/auth/sms/verify",
        timeout_seconds=timeout_seconds,
        payload={"phone_number": phone, "code": code},
        access_token=None,
    )
    token = response.get("access_token")
    if not isinstance(token, str) or not token:
        raise SmokeError("auth response did not include access_token")
    return token


def create_conversation(base_url: str, access_token: str, timeout_seconds: int) -> str:
    response = request_json(
        "POST",
        f"{base_url}/conversations",
        timeout_seconds=timeout_seconds,
        payload={"title": "ASR OSS smoke test"},
        access_token=access_token,
    )
    conversation_id = response.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise SmokeError("conversation response did not include conversation_id")
    return conversation_id


def create_oss_upload(
    base_url: str,
    access_token: str,
    label: str,
    url: str,
    timeout_seconds: int,
) -> str:
    response = request_json(
        "POST",
        f"{base_url}/uploads",
        timeout_seconds=timeout_seconds,
        payload={
            "storage_provider": "oss",
            "object_key": url,
            "mime_type": guess_mime_type(label, url),
            "source": "microphone",
            "retention_policy": "transient",
        },
        access_token=access_token,
    )
    file_info = response.get("file")
    if not isinstance(file_info, dict):
        raise SmokeError("upload response did not include file")
    file_id = file_info.get("id")
    if not isinstance(file_id, str) or not file_id:
        raise SmokeError("upload response did not include file.id")
    return file_id


def send_audio_message(
    base_url: str,
    access_token: str,
    conversation_id: str,
    file_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    return request_json(
        "POST",
        f"{base_url}/conversations/{conversation_id}/messages",
        timeout_seconds=timeout_seconds,
        payload={
            "content": [
                {
                    "type": "text",
                    "text": "这是一段测试语音，请转写并整理成待确认记录。",
                },
                {
                    "type": "audio",
                    "file_id": file_id,
                    "duration_seconds": 10,
                },
            ]
        },
        access_token=access_token,
    )


def request_json(
    method: str,
    url: str,
    timeout_seconds: int,
    payload: dict[str, Any] | None,
    access_token: str | None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = f"{method} {redact_query(url)} failed with HTTP {exc.code}: {detail}"
        raise SmokeError(message) from exc
    except (URLError, TimeoutError) as exc:
        raise SmokeError(f"{method} {redact_query(url)} failed: {exc}") from exc

    if not isinstance(raw, dict):
        raise SmokeError(f"{method} {redact_query(url)} returned non-object JSON")
    if raw.get("error"):
        raise SmokeError(f"{method} {redact_query(url)} returned error: {raw['error']}")
    data = raw.get("data")
    if not isinstance(data, dict):
        raise SmokeError(f"{method} {redact_query(url)} returned missing data object")
    return data


def print_api_result(result: dict[str, Any]) -> None:
    print("status: message_sent")
    print(f"intent: {result.get('intent')}")
    print(f"requires_review: {result.get('requires_review')}")
    assistant_text = result.get("assistant_text")
    if assistant_text:
        print(f"assistant_text: {assistant_text}")
    pending_actions = result.get("pending_actions") or []
    if isinstance(pending_actions, list):
        action_types = [
            item.get("type")
            for item in pending_actions
            if isinstance(item, dict) and isinstance(item.get("type"), str)
        ]
        print(f"pending_actions: {', '.join(action_types) if action_types else '-'}")


def guess_mime_type(label: str, url: str) -> str:
    parsed_path = unquote(urlparse(url).path)
    mime_type, _encoding = mimetypes.guess_type(parsed_path or label)
    return mime_type or "audio/mp4"


def redact_query(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="...").geturl() if parsed.query else url


class SmokeError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
