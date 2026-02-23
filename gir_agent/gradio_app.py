"""Gradio UI for Gir Agent.

This module provides a lightweight Gradio interface combining a chat window
with a live HTML map viewer. The map viewer renders the most recent Folium
HTML produced by the `visualize_geojson` tool (stored in
`state['user:last_geo_map_path']`).
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from gir_agent.agent import root_agent

APP_NAME = "gir_agent"
USER_ID = "gradio_user"

_artifact_service = InMemoryArtifactService()
_session_service = InMemorySessionService()
_session = None
_runner: Runner | None = None
_lock = asyncio.Lock()
_logs: deque[str] = deque(maxlen=500)
MAP_FRAME_HEIGHT_PX = 520
CESIUM_IMAGERY_URL = (
    "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer?f=jsapi"
)


def _append_log(line: str) -> None:
    """Append a timestamped log line to the in-memory buffer."""

    ts = datetime.utcnow().strftime("%H:%M:%S")
    _logs.append(f"[{ts}] {line}")


def _format_logs() -> str:
    if not _logs:
        return "No server logs yet."
    return "\n".join(_logs)


class _BufferLogHandler(logging.Handler):
    """In-memory log handler used to surface server logs in the UI."""

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        _append_log(message)


# Capture INFO+ logs from the root logger so we surface operational details.
logging.basicConfig(level=logging.INFO, handlers=[_BufferLogHandler()])


def _escape_for_iframe(doc: str) -> str:
    """Wrap arbitrary HTML in an iframe via srcdoc, escaping safely."""

    escaped = html_lib.escape(doc)
    return (
        f"<iframe style=\"width:100%;height:{MAP_FRAME_HEIGHT_PX}px;border:1px solid #d7d7e0;"
        "border-radius:12px;\" srcdoc=\"" + escaped + "\"></iframe>"
    )


def _looks_like_wkt(value: str) -> bool:
    upper = value.strip().upper()
    return upper.startswith(
        (
            "POINT",
            "LINESTRING",
            "POLYGON",
            "MULTIPOINT",
            "MULTILINESTRING",
            "MULTIPOLYGON",
        )
    )


def _collect_wkts(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if _looks_like_wkt(value) else []
    if isinstance(value, dict):
        results: List[str] = []
        for item in value.values():
            results.extend(_collect_wkts(item))
        return results
    if isinstance(value, (list, tuple, set)):
        results: List[str] = []
        for item in value:
            results.extend(_collect_wkts(item))
        return results
    return []


def _wkt_to_geojson(value: str) -> Optional[Dict[str, Any]]:
    from gir_agent.web_app import _wkt_to_geojson as _shared_wkt_to_geojson

    return _shared_wkt_to_geojson(value)


def _state_to_geojson(state: Dict[str, Any]) -> Dict[str, Any]:
    wkts = _collect_wkts(state)
    features = []
    for wkt in wkts:
        geometry = _wkt_to_geojson(wkt)
        if geometry:
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {},
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _build_cesium_map_html(geojson: Dict[str, Any]) -> str:
    encoded_geojson = json.dumps(geojson)
    encoded_imagery_url = json.dumps(CESIUM_IMAGERY_URL)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link href="https://unpkg.com/cesium/Build/Cesium/Widgets/widgets.css" rel="stylesheet" />
  <style>
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: #0a0d16;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/cesium/Build/Cesium/Cesium.js"></script>
  <script>
    const viewer = new Cesium.Viewer('map', {{
      imageryProvider: false,
      baseLayerPicker: false,
      geocoder: false,
      timeline: false,
      animation: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      selectionIndicator: false,
      infoBox: false
    }});

    const provider = new Cesium.WebMapServiceImageryProvider({{
      url: {encoded_imagery_url},
      layers: '0'
    }});
    viewer.imageryLayers.add(new Cesium.ImageryLayer(provider));

    const geojson = {encoded_geojson};
    Cesium.GeoJsonDataSource.load(geojson, {{ clampToGround: true }})
      .then((source) => {{
        viewer.dataSources.add(source);
        if (geojson.features && geojson.features.length) {{
          viewer.flyTo(source);
        }}
      }})
      .catch(() => {{}});
  </script>
</body>
</html>"""


def _load_map_html() -> str:
    """Load the latest map HTML recorded in session state, if any."""

    if not _session:
        return _fallback_map()

    state: dict[str, Any] = getattr(_session, "state", {}) or {}
    geojson = _state_to_geojson(state)
    if geojson.get("features"):
        return _escape_for_iframe(_build_cesium_map_html(geojson))

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
        f"<div style=\"height:{MAP_FRAME_HEIGHT_PX}px;padding:18px;border:1px dashed #ccc;"
        "border-radius:12px;background:#fafafa;font-family:Inter, sans-serif;"
        "display:flex;flex-direction:column;justify-content:center;\">"
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
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            author = getattr(event, "author", "server")
            text = _extract_text(event)
            if text:
                reply = text
                _append_log(f"{author}: {text}")

    map_html = _load_map_html()
    return reply, map_html


def _extract_text(event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts)


async def respond_stream(message: str, history: List[dict[str, str]]):
    """Stream assistant messages to the chatbot while the agent runs."""

    _append_log(f"user: {message}")
    history = history + [{"role": "user", "content": message}]
    assistant_entry = {"role": "assistant", "content": ""}
    history.append(assistant_entry)

    await _ensure_session()
    async with _lock:
        assert _runner is not None and _session is not None
        async for event in _runner.run_async(
            user_id=_session.user_id,
            session_id=_session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            author = getattr(event, "author", "server")
            text = _extract_text(event)
            if not text:
                continue
            # Prefer token/partial deltas; fall back to full text replacement.
            existing = assistant_entry["content"]
            addition = text[len(existing) :] if text.startswith(existing) else text
            if addition:
                assistant_entry["content"] = existing + addition
                _append_log(f"{author}: {addition}")
                # Stream partial assistant text; map refresh at end of loop
                yield history, _load_map_html(), _format_logs()

    # Final yield ensures map is latest after run finishes
    yield history, _load_map_html(), _format_logs()


async def refresh_map(history: List[dict[str, str]]):
    """Refresh only the map panel without sending a new message."""

    return history, _load_map_html(), _format_logs()


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

        with gr.Row():
            log_box = gr.Textbox(
                label="Server Logs",
                value=_format_logs(),
                lines=12,
                interactive=False,
            )

        send_btn.click(
            respond_stream,
            inputs=[msg, chatbot],
            outputs=[chatbot, map_view, log_box],
        )
        msg.submit(
            respond_stream, inputs=[msg, chatbot], outputs=[chatbot, map_view, log_box]
        )
        msg.submit(lambda: "", None, msg)  # clear after submit
        refresh_btn.click(
            refresh_map, inputs=[chatbot], outputs=[chatbot, map_view, log_box]
        )

    return demo


if __name__ == "__main__":
    ui = build_ui()
    ui.queue().launch(server_name="0.0.0.0", server_port=8010)
