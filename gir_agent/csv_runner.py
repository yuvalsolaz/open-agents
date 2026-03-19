import argparse
import asyncio
import csv
import sys
from typing import Any

APP_NAME = "gir_agent"
USER_ID = "csv_runner"
REQUIRED_COLUMNS = ("id", "query")


def _extract_text(event: Any) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts)


async def _run_query(
    runner: Any,
    session_service: Any,
    query: str,
) -> str:
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.genai import types

    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    reply = ""
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=query)]),
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        text = _extract_text(event)
        if text:
            reply = text
    return reply


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gir Agent over a CSV dataset and write results to a new CSV.",
    )
    parser.add_argument("--input-csv", required=True, help="Path to the input CSV.")
    parser.add_argument("--output-csv", required=True, help="Path to the output CSV.")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Print progress every N rows. Use 0 to disable.",
    )
    return parser.parse_args()


def _validate_fieldnames(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        raise ValueError("Input CSV is missing a header row.")

    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Input CSV is missing required columns: {missing_text}")

    return fieldnames


async def _run_batch(args: argparse.Namespace) -> int:
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    from gir_agent.agent import root_agent

    artifact_service = InMemoryArtifactService()
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        artifact_service=artifact_service,
        session_service=session_service,
    )

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

                for row in reader:
                    total_rows += 1
                    output_row = dict(row)
                    query = (row.get("query") or "").strip()

                    if not query:
                        output_row["agent_output"] = ""
                        output_row["status"] = "error"
                        output_row["error_message"] = "Query is empty."
                        failed_rows += 1
                    else:
                        try:
                            output_row["agent_output"] = await _run_query(
                                runner=runner,
                                session_service=session_service,
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

                    writer.writerow(output_row)

                    if args.progress_every and total_rows % args.progress_every == 0:
                        print(
                            f"Processed {total_rows} rows "
                            f"(ok={success_rows}, error={failed_rows})",
                            file=sys.stderr,
                        )
    finally:
        await runner.close()

    print(
        f"Finished {total_rows} rows (ok={success_rows}, error={failed_rows}).",
        file=sys.stderr,
    )
    return 0 if failed_rows == 0 else 1


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run_batch(args))
    except ModuleNotFoundError as exc:
        print(
            f"Missing dependency: {exc}. Install project requirements before running the CSV batch runner.",
            file=sys.stderr,
        )
        return 3
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
