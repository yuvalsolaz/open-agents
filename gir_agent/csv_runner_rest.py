import argparse
import csv
import sys
import uuid
from typing import Any
from urllib.parse import quote

APP_NAME = "gir_agent"
BASE_URL = "http://localhost:8000"
USER_ID = "csv_runner_rest"
REQUIRED_COLUMNS = ("id", "query")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gir Agent over a CSV dataset via the Google ADK REST API.",
    )
    parser.add_argument("--input-csv", required=True, help="Path to the input CSV.")
    parser.add_argument("--output-csv", required=True, help="Path to the output CSV.")
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="Base URL of the ADK API server.",
    )
    parser.add_argument(
        "--app-name",
        default=APP_NAME,
        help="ADK app name exposed by the API server.",
    )
    parser.add_argument(
        "--user-id",
        default=USER_ID,
        help="User ID prefix used for created sessions.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print progress every N rows. Use 0 to disable.",
    )
    parser.add_argument(
        "--keep-sessions",
        action="store_true",
        help="Do not delete sessions from the ADK server after each row.",
    )
    return parser.parse_args()


def _validate_fieldnames(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        raise ValueError("Input CSV is missing a header row.")

    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            f"Input CSV is missing required columns: {', '.join(missing)}"
        )

    return fieldnames


def _extract_text_from_events(events: list[dict[str, Any]]) -> str:
    reply = ""
    for event in events:
        content = event.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            text = part.get("text")
            if text:
                reply = text
    return reply


def _session_url(base_url: str, app_name: str, user_id: str, session_id: str) -> str:
    return (
        f"{base_url.rstrip('/')}/apps/{quote(app_name, safe='')}"
        f"/users/{quote(user_id, safe='')}/sessions/{quote(session_id, safe='')}"
    )


def _create_session(
    client: Any,
    base_url: str,
    app_name: str,
    user_id: str,
    session_id: str,
) -> None:
    response = client.post(
        _session_url(base_url, app_name, user_id, session_id),
        json={},
    )
    response.raise_for_status()


def _delete_session(
    client: Any,
    base_url: str,
    app_name: str,
    user_id: str,
    session_id: str,
) -> None:
    response = client.delete(_session_url(base_url, app_name, user_id, session_id))
    response.raise_for_status()


def _run_query(
    client: Any,
    base_url: str,
    app_name: str,
    user_id: str,
    session_id: str,
    query: str,
) -> str:
    response = client.post(
        f"{base_url.rstrip('/')}/run",
        json={
            "appName": app_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": {
                "role": "user",
                "parts": [{"text": query}],
            },
        },
    )
    response.raise_for_status()
    events = response.json()
    if not isinstance(events, list):
        raise ValueError("ADK /run response was not a list of events.")
    return _extract_text_from_events(events)


def main() -> int:
    args = _parse_args()

    try:
        import httpx
    except ModuleNotFoundError as exc:
        print(
            f"Missing dependency: {exc}. Install project requirements before running the REST CSV runner.",
            file=sys.stderr,
        )
        return 3

    total_rows = 0
    success_rows = 0
    failed_rows = 0

    try:
        with open(args.input_csv, "r", encoding="utf-8", newline="") as input_file:
            reader = csv.DictReader(input_file)
            input_columns = _validate_fieldnames(reader.fieldnames)
            output_columns = input_columns + ["agent_output", "status", "error_message"]

            with open(args.output_csv, "w", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(output_file, fieldnames=output_columns)
                writer.writeheader()

                with httpx.Client(timeout=300.0) as client:
                    for row in reader:
                        total_rows += 1
                        output_row = dict(row)
                        query = (row.get("query") or "").strip()
                        session_id = f"row-{row.get('id', total_rows)}-{uuid.uuid4().hex[:8]}"

                        if not query:
                            output_row["agent_output"] = ""
                            output_row["status"] = "error"
                            output_row["error_message"] = "Query is empty."
                            failed_rows += 1
                            writer.writerow(output_row)
                            continue

                        try:
                            _create_session(
                                client=client,
                                base_url=args.base_url,
                                app_name=args.app_name,
                                user_id=args.user_id,
                                session_id=session_id,
                            )
                            output_row["agent_output"] = _run_query(
                                client=client,
                                base_url=args.base_url,
                                app_name=args.app_name,
                                user_id=args.user_id,
                                session_id=session_id,
                                query=query,
                            )
                            output_row["status"] = "ok"
                            output_row["error_message"] = ""
                            success_rows += 1
                        except Exception as exc:
                            output_row["agent_output"] = ""
                            output_row["status"] = "error"
                            output_row["error_message"] = str(exc)
                            failed_rows += 1
                        finally:
                            if not args.keep_sessions:
                                try:
                                    _delete_session(
                                        client=client,
                                        base_url=args.base_url,
                                        app_name=args.app_name,
                                        user_id=args.user_id,
                                        session_id=session_id,
                                    )
                                except Exception:
                                    pass

                        writer.writerow(output_row)

                        if args.progress_every and total_rows % args.progress_every == 0:
                            print(
                                f"Processed {total_rows} rows "
                                f"(ok={success_rows}, error={failed_rows})",
                                file=sys.stderr,
                            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        f"Finished {total_rows} rows (ok={success_rows}, error={failed_rows}).",
        file=sys.stderr,
    )
    return 0 if failed_rows == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
