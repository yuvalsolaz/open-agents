"""Gradio UI for Gir Agent.

This module provides a lightweight Gradio interface combining a chat window
with a live HTML map viewer. The map viewer renders the most recent Folium
HTML produced by the `visualize_geojson` tool (stored in
`state['user:last_geo_map_path']`).
"""

from __future__ import annotations

import asyncio
import html as html_lib
from pathlib import Path
from typing import Any, List, Tuple

import gradio as gr
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from gir_agent.agent import root_agent

APP_NAME = "gir_agent"
USER_ID = "gradio_user"

_artifact_service = InMemoryArtifactService()
_session_service = InMemorySessionService()
_session = None
_runner: Runner | None = None
_lock = asyncio.Lock()


def _escape_for_iframe(doc: str) -> str:
    """Wrap arbitrary HTML in an iframe via srcdoc, escaping safely."""

    escaped = html_lib.escape(doc)
    return (
        "<iframe style=\"width:100%;height:520px;border:1px solid #d7d7e0;"
        "border-radius:12px;\" srcdoc=\"" + escaped + "\"></iframe>"
    )


def _load_map_html() -> str:
    """Load the latest map HTML recorded in session state, if any."""

    if not _session:
        return _fallback_map()

    state: dict[str, Any] = getattr(_session, "state", {}) or {}
    map_path = state.get("user:last_geo_map_path")
    if not map_path:
        map_path = _discover_latest_map_path()

    if map_path:
        file = Path(map_path)
        if file.exists():
            try:
                content = file.read_text(encoding="utf-8")
                return _escape_for_iframe(content)
            except Exception:
                return _fallback_map("Could not read the last map file.")

    # If no explicit path, fall back to inline notice.
    return _fallback_map()


def _fallback_map(message: str | None = None) -> str:
    note = message or "No map available yet. Run a geo query to generate one."
    return (
        "<div style=\"padding:18px;border:1px dashed #ccc;"
        "border-radius:12px;background:#fafafa;font-family:Inter, sans-serif;\">"
        f"<strong>Map</strong><br><span>{html_lib.escape(note)}</span></div>"
    )


def _discover_latest_map_path() -> str | None:
    """Find the most recent map HTML saved under build/maps when state is missing."""

    maps_dir = Path.cwd() / "build" / "maps"
    if not maps_dir.exists():
        return None
    html_files = sorted(
        maps_dir.glob("geo_map_*.html"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return str(html_files[0]) if html_files else None


async def _ensure_session() -> None:
    global _session, _runner
    if _session and _runner:
        return

    _session = await _session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    _runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        artifact_service=_artifact_service,
        session_service=_session_service,
    )


async def _chat_once(message: str) -> Tuple[str, str]:
    """Send a message to the agent and return (reply, map_html)."""

    await _ensure_session()
    reply = ""
    async with _lock:
        assert _runner is not None and _session is not None
        async for event in _runner.run_async(
            user_id=_session.user_id,
            session_id=_session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            text = _extract_text(event)
            if text:
                reply = text

    map_html = _load_map_html()
    return reply, map_html


def _extract_text(event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts)


async def respond(message: str, history: List[dict[str, str]]):
    """Gradio handler: update chat history (role/content pairs) and map."""

    reply, map_html = await _chat_once(message)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    return history, map_html


async def refresh_map(history: List[dict[str, str]]):
    """Refresh only the map panel without sending a new message."""

    return history, _load_map_html()


def build_ui() -> gr.Blocks:
    """Construct the Gradio Blocks interface."""

    with gr.Blocks(title="Gir Agent - Gradio") as demo:
        gr.Markdown(
            """
            # Gir Agent
            Chat with the geo-intelligence agent. After a geo query, the latest
            Folium map artifact is shown on the right.
            """
        )

        with gr.Row():
            # Chatbot expects list of {role, content} messages in Gradio 6.x.
            chatbot = gr.Chatbot(height=480)
            map_view = gr.HTML(value=_fallback_map(), label="Latest Map")

        with gr.Row():
            msg = gr.Textbox(
                label="Message",
                placeholder="Ask about locations, routes, or general questions...",
                lines=3,
            )
            send_btn = gr.Button("Send", variant="primary")
            refresh_btn = gr.Button("Refresh Map")

        send_btn.click(respond, inputs=[msg, chatbot], outputs=[chatbot, map_view])
        msg.submit(respond, inputs=[msg, chatbot], outputs=[chatbot, map_view])
        msg.submit(lambda: "", None, msg)  # clear after submit
        refresh_btn.click(refresh_map, inputs=[chatbot], outputs=[chatbot, map_view])

    return demo


if __name__ == "__main__":
    ui = build_ui()
    ui.queue().launch(server_name="0.0.0.0", server_port=8010)
