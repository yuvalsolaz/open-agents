# open-agents

## Gir Agent chat

Run a simple terminal chat session with the Gir agent:

```bash
python -m gir_agent.chat_interface
```

## Gir Agent web chat

Run a web UI for the Gir agent:

```bash
python -m gir_agent.web_app
```

Then open `http://localhost:8000`.

Map notes:
- The map uses Cesium with the USGS Hydro WMS layer via `/proxy/`.
- WKT geometries stored in the session state are rendered automatically.
