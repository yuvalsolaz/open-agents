"""GeoJSON visualization tool.

This tool reads GeoJSON data from the tool context, renders it with Folium
into an interactive HTML map, writes the map to disk, and saves the HTML as a
session artifact.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import folium
from google.adk.tools import ToolContext
from google.genai import types


def _extract_geojson(tool_context: ToolContext) -> Optional[dict[str, Any]]:
    """Fetches GeoJSON from the tool context, checking common keys."""

    # Prefer explicit state keys that other tools (geo_coding) already set.
    state = getattr(tool_context, "state", None)
    if state:
        geo_json = state.get("geo_json") or state.get("user:geo_json")
        if geo_json:
            return geo_json

    # Fallback: attempt mapping-style access if provided by the runtime.
    try:  # type: ignore[index]
        return tool_context["geo_json"]  # type: ignore[index]
    except Exception:
        return None


def _compute_center(geo_json: dict[str, Any]) -> Optional[tuple[float, float]]:
    """Calculates an average (lat, lon) center from GeoJSON Point features."""

    coords: list[tuple[float, float]] = []
    for feature in geo_json.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        raw = geometry.get("coordinates") or []
        if len(raw) < 2:
            continue
        lon, lat = raw[:2]
        coords.append((float(lat), float(lon)))

    if not coords:
        return None

    lat_sum = sum(lat for lat, _ in coords)
    lon_sum = sum(lon for _, lon in coords)
    count = len(coords)
    return (lat_sum / count, lon_sum / count)


async def visualize_geojson(tool_context: ToolContext) -> dict[str, Any]:
    """Render GeoJSON to an HTML map and store it as an artifact.

    The function expects GeoJSON to be present in the tool context (commonly
    under `state['geo_json']` or `state['user:geo_json']`). The map is saved to
    `/maps` and also attached to the current session as an HTML artifact.

    Returns a small dict with the local file path and artifact version.
    """

    geo_json = _extract_geojson(tool_context)
    if not geo_json:
        return {"error": "No GeoJSON found in tool_context."}

    center = _compute_center(geo_json) or (0.0, 0.0)
    zoom_start = 10 if center != (0.0, 0.0) else 2

    # Build the folium map
    fmap = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)
    folium.GeoJson(
        geo_json,
        name="geojson",
        tooltip=folium.features.GeoJsonTooltip(
            fields=["display_name", "address"],
            aliases=["Name", "Address"],
            labels=True,
            localize=True,
        ),
    ).add_to(fmap)

    # Add simple markers for easy clicking
    for feature in geo_json.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[:2]
        props = feature.get("properties") or {}
        popup_text = props.get("display_name") or props.get("address")
        folium.Marker(location=(lat, lon), popup=popup_text).add_to(fmap)

    fmap.add_child(folium.LayerControl())

    # Persist to disk
    output_dir = Path.cwd() / "maps"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"geo_map_{timestamp}.html"
    file_path = output_dir / filename

    html_content = fmap.get_root().render()
    file_path.write_text(html_content, encoding="utf-8")

    # Save as artifact (embed the HTML bytes)
    html_part = types.Part.from_bytes(
        data=html_content.encode("utf-8"), mime_type="text/html"
    )
    version = await tool_context.save_artifact(
        filename=filename,
        artifact=html_part,
        custom_metadata={"path": str(file_path)},
    )

    # Keep location handy in state for later tools
    tool_context.state["user:last_geo_map_path"] = str(file_path)

    return {"file_path": str(file_path), "artifact_version": version}
