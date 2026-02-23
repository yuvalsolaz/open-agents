import asyncio
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

from gir_agent.agent import root_agent

APP_NAME = "gir_agent"
USER_ID = "web_user"

app = FastAPI()

_artifact_service = InMemoryArtifactService()
_session_service = InMemorySessionService()
_session = None
_runner = None
_lock = asyncio.Lock()

_proxy_base = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/?callback=loadJsonp905915&f=json'


def _extract_text(event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts)


def _strip_outer_parens(value: str) -> str:
    value = value.strip()
    if value.startswith("(") and value.endswith(")"):
        return value[1:-1].strip()
    return value


def _split_top_level_groups(value: str) -> List[str]:
    groups: List[str] = []
    depth = 0
    start = None
    for idx, ch in enumerate(value):
        if ch == "(":
            depth += 1
            if depth == 1:
                start = idx + 1
        elif ch == ")":
            if depth == 1 and start is not None:
                groups.append(value[start:idx].strip())
                start = None
            depth -= 1
    return groups


def _parse_point(value: str) -> Optional[List[float]]:
    parts = [p for p in value.replace(",", " ").split() if p]
    if len(parts) < 2:
        return None
    try:
        return [float(parts[0]), float(parts[1])]
    except ValueError:
        return None


def _parse_line(value: str) -> Optional[List[List[float]]]:
    points = []
    for chunk in value.split(","):
        point = _parse_point(chunk)
        if point is None:
            return None
        points.append(point)
    return points


def _wkt_to_geojson(value: str) -> Optional[Dict[str, Any]]:
    raw = value.strip()
    if not raw:
        return None
    geom_type = raw.split("(", 1)[0].strip().upper()
    body = raw[len(geom_type) :].strip()
    body = _strip_outer_parens(body)

    if geom_type == "POINT":
        coords = _parse_point(body)
        return {"type": "Point", "coordinates": coords} if coords else None
    if geom_type == "LINESTRING":
        coords = _parse_line(body)
        return {"type": "LineString", "coordinates": coords} if coords else None
    if geom_type == "POLYGON":
        rings = _split_top_level_groups(body) if "(" in body else [body]
        coords = []
        for ring in rings:
            line = _parse_line(ring)
            if line is None:
                return None
            coords.append(line)
        return {"type": "Polygon", "coordinates": coords}
    if geom_type == "MULTIPOINT":
        if "(" in body:
            groups = _split_top_level_groups(body)
            coords = [_parse_point(group) for group in groups]
        else:
            coords = [_parse_point(chunk) for chunk in body.split(",")]
        if any(point is None for point in coords):
            return None
        return {"type": "MultiPoint", "coordinates": coords}
    if geom_type == "MULTILINESTRING":
        groups = _split_top_level_groups(body)
        coords = []
        for group in groups:
            line = _parse_line(group)
            if line is None:
                return None
            coords.append(line)
        return {"type": "MultiLineString", "coordinates": coords}
    if geom_type == "MULTIPOLYGON":
        groups = _split_top_level_groups(body)
        coords = []
        for group in groups:
            polygon_body = _strip_outer_parens(group)
            rings = _split_top_level_groups(polygon_body)
            polygon = []
            for ring in rings:
                line = _parse_line(ring)
                if line is None:
                    return None
                polygon.append(line)
            coords.append(polygon)
        return {"type": "MultiPolygon", "coordinates": coords}
    return None


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
        results = []
        for item in value:
            results.extend(_collect_wkts(item))
        return results
    return []


@app.on_event("startup")
async def _startup() -> None:
    global _session, _runner
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


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _runner:
        await _runner.close()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Gir Agent Chat</title>
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Fraunces:wght@500;700&family=Space+Grotesk:wght@400;600&display=swap\" rel=\"stylesheet\">
  <link href=\"https://unpkg.com/cesium/Build/Cesium/Widgets/widgets.css\" rel=\"stylesheet\">
  <style>
    :root {
      --bg: #0b0f1f;
      --bg-2: #1c0f2e;
      --panel: rgba(14, 18, 40, 0.78);
      --accent: #ffb347;
      --accent-2: #69f0d4;
      --text: #f6f4ff;
      --muted: #c2c6e8;
      --shadow: 0 30px 80px rgba(7, 10, 26, 0.45);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Space Grotesk", system-ui, sans-serif;
      color: var(--text);
      background: radial-gradient(900px circle at 10% -10%, #2a214b 0%, transparent 50%),
                  radial-gradient(700px circle at 90% 10%, #1a3d4a 0%, transparent 45%),
                  linear-gradient(120deg, var(--bg), var(--bg-2));
      padding: 32px 16px;
      overflow: hidden;
    }

    .shell {
      width: min(1200px, 100%);
      height: calc(100vh - 64px);
      max-height: 100%;
      background: var(--panel);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
      border: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(16px);
      animation: fadeUp 0.8s ease both;
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 0;
    }

    header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
    }

    .brand {
      font-family: "Fraunces", serif;
      font-size: clamp(1.6rem, 2vw, 2.3rem);
      letter-spacing: 0.5px;
    }

    .tagline {
      color: var(--muted);
      font-size: 0.95rem;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.2fr);
      grid-template-rows: minmax(0, 1fr);
      gap: 20px;
      height: 100%;
      min-height: 0;
    }

    .chat-shell {
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto auto;
      height: 100%;
      min-height: 0;
    }

    .chat {
      height: 100%;
      min-height: 0;
      overflow-y: auto;
      padding: 18px;
      background: rgba(8, 10, 24, 0.55);
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.08);
    }

    .bubble {
      max-width: 78%;
      padding: 14px 16px;
      margin-bottom: 14px;
      border-radius: 16px;
      line-height: 1.4;
      animation: floatIn 0.4s ease both;
    }

    .bubble.user {
      margin-left: auto;
      background: linear-gradient(135deg, rgba(255, 179, 71, 0.9), rgba(255, 209, 129, 0.9));
      color: #1a1024;
      font-weight: 600;
    }

    .bubble.agent {
      margin-right: auto;
      background: linear-gradient(135deg, rgba(105, 240, 212, 0.2), rgba(116, 161, 255, 0.2));
      border: 1px solid rgba(105, 240, 212, 0.3);
    }

    .map-shell {
      border-radius: 18px;
      overflow: hidden;
      border: 1px solid rgba(255, 255, 255, 0.08);
      background: rgba(8, 10, 24, 0.55);
      display: grid;
      grid-template-rows: auto 1fr;
      height: 100%;
      min-height: 0;
    }

    .map-header {
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      background: rgba(12, 16, 34, 0.7);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }

    .map-title {
      font-weight: 600;
    }

    .map-actions button {
      height: 40px;
      padding: 0 16px;
      font-size: 0.9rem;
    }

    #map {
      width: 100%;
      height: 100%;
      min-height: 0;
    }

    .composer {
      margin-top: 18px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
    }

    textarea {
      resize: none;
      min-height: 56px;
      max-height: 140px;
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: rgba(8, 10, 24, 0.8);
      color: var(--text);
      padding: 14px 16px;
      font-family: inherit;
      font-size: 1rem;
      outline: none;
    }

    button {
      border: none;
      border-radius: 16px;
      padding: 0 24px;
      font-weight: 600;
      font-size: 1rem;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #111018;
      cursor: pointer;
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      box-shadow: 0 14px 30px rgba(255, 179, 71, 0.25);
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      box-shadow: none;
    }

    button:not(:disabled):hover {
      transform: translateY(-2px);
      box-shadow: 0 20px 40px rgba(105, 240, 212, 0.25);
    }

    .status {
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(24px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @keyframes floatIn {
      from { opacity: 0; transform: translateY(10px) scale(0.98); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    @media (max-width: 720px) {
      body { padding: 8px; }
      .shell {
        height: calc(100vh - 16px);
        padding: 20px;
      }
      .layout {
        grid-template-columns: 1fr;
        grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
        height: 100%;
      }
      .bubble { max-width: 92%; }
      .composer { grid-template-columns: 1fr; }
      button { height: 48px; }
    }
  </style>
</head>
<body>
  <div class=\"shell\">
    <header>
      <div class=\"brand\">Gir Agent</div>
      <div class=\"tagline\">Web chat for orchestrating research + geo intelligence.</div>
    </header>

    <section class=\"layout\">
      <div class=\"chat-shell\">
        <main class=\"chat\" id=\"chat\"></main>

        <form class=\"composer\" id=\"composer\">
          <textarea id=\"input\" placeholder=\"Ask the Gir agent anything...\" required></textarea>
          <button id=\"send\" type=\"submit\">Send</button>
        </form>

        <div class=\"status\" id=\"status\">Ready.</div>
      </div>

      <div class=\"map-shell\">
        <div class=\"map-header\">
          <div class=\"map-title\">Geo Context</div>
          <div class=\"map-actions\">
            <button id=\"refresh\">Sync Map</button>
          </div>
        </div>
        <div id=\"map\"></div>
      </div>
    </section>
  </div>

  <script src=\"https://unpkg.com/cesium/Build/Cesium/Cesium.js\"></script>
  <script>
    const chat = document.getElementById('chat');
    const form = document.getElementById('composer');
    const input = document.getElementById('input');
    const status = document.getElementById('status');
    const send = document.getElementById('send');
    const refreshBtn = document.getElementById('refresh');

    const viewer = new Cesium.Viewer('map', {
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
    });

    const provider = new Cesium.WebMapServiceImageryProvider({
      url: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/?callback=loadJsonp905915&f=json',
      layers: '0',
      proxy: new Cesium.DefaultProxy('/proxy/')
    });
    const imageryLayer = new Cesium.ImageryLayer(provider);
    viewer.imageryLayers.add(imageryLayer);

    let geoSource = null;
    let didFirstLocationZoomOut = false;

    function firstPointFromGeoJson(geojson) {
      const features = geojson && Array.isArray(geojson.features) ? geojson.features : [];
      for (const feature of features) {
        const geometry = feature && feature.geometry ? feature.geometry : null;
        if (!geometry) continue;

        if (geometry.type === 'Point' && Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2) {
          return geometry.coordinates;
        }

        if (geometry.type === 'MultiPoint' && Array.isArray(geometry.coordinates) && geometry.coordinates.length) {
          const point = geometry.coordinates[0];
          if (Array.isArray(point) && point.length >= 2) {
            return point;
          }
        }
      }
      return null;
    }

    async function refreshMap() {
      try {
        const res = await fetch('/features');
        if (!res.ok) return;
        const geojson = await res.json();
        if (geoSource) {
          viewer.dataSources.remove(geoSource, true);
        }
        geoSource = await Cesium.GeoJsonDataSource.load(geojson, {
          clampToGround: true
        });
        viewer.dataSources.add(geoSource);
        if (geojson.features && geojson.features.length) {
          const firstPoint = firstPointFromGeoJson(geojson);
          if (!didFirstLocationZoomOut && firstPoint) {
            const [lon, lat] = firstPoint;
            const destination = Cesium.Cartesian3.fromDegrees(lon, lat, 25000.0);
            viewer.camera.flyTo({
              destination,
              duration: 1.5
            });
            didFirstLocationZoomOut = true;
          } else {
            viewer.flyTo(geoSource);
          }
        }
      } catch (err) {
        // keep quiet; chat still works
      }
    }

    refreshBtn.addEventListener('click', refreshMap);

    function addBubble(text, who) {
      const bubble = document.createElement('div');
      bubble.className = `bubble ${who}`;
      bubble.textContent = text;
      chat.appendChild(bubble);
      chat.scrollTop = chat.scrollHeight;
    }

    async function sendMessage(message) {
      status.textContent = 'Thinking...';
      send.disabled = true;
      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message })
        });
        if (!res.ok) {
          throw new Error('Request failed');
        }
        const data = await res.json();
        addBubble(data.reply || 'No response.', 'agent');
        status.textContent = 'Ready.';
        refreshMap();
      } catch (err) {
        status.textContent = 'Error talking to Gir Agent.';
        addBubble('Sorry, something went wrong.', 'agent');
      } finally {
        send.disabled = false;
      }
    }

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      addBubble(message, 'user');
      input.value = '';
      sendMessage(message);
    });

    refreshMap();
    setInterval(refreshMap, 7000);
  </script>
</body>
</html>"""


@app.post("/chat")
async def chat(payload: Dict[str, str]) -> JSONResponse:
    message = (payload.get("message") or "").strip()
    if not message:
        return JSONResponse({"reply": ""})

    async with _lock:
        reply = ""
        async for event in _runner.run_async(
            user_id=_session.user_id,
            session_id=_session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            text = _extract_text(event)
            if text:
                reply = text

    return JSONResponse({"reply": reply})


@app.get("/features")
async def features() -> JSONResponse:
    state = _session.state if _session else {}
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
    return JSONResponse({"type": "FeatureCollection", "features": features})


@app.get("/proxy/")
async def proxy(url: str, request: Request) -> Response:
    target = unquote(url)
    if not target.startswith(_proxy_base):
        raise HTTPException(status_code=400, detail="Proxy target not allowed.")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(target)
    content_type = response.headers.get("content-type", "application/octet-stream")
    return Response(content=response.content, media_type=content_type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("gir_agent.web_app:app", host="0.0.0.0", port=8009, reload=True)
