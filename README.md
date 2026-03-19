# open-agents

A small geo-focused multi-agent application built on **Google ADK**, with three user interfaces:

- **CLI** (terminal chat)
- **FastAPI Web App** (custom chat UI + Cesium map)
- **Gradio App** (chat + map panel + logs)

The app follows a structured workflow: extract locations → enrich via web search → geocode via OpenStreetMap → produce a top-3 geo report + map artifacts.

---

## Features

- Multi-agent orchestration using Google ADK
- Location extraction + enrichment via search sub-agent
- Geocoding via OSM (Nominatim) and GeoJSON feature generation
- Interactive maps rendered to HTML (Folium)
- Multiple UIs (CLI / FastAPI / Gradio)

---

## Repository Structure

### Core Architecture

1. **Orchestrator agent**
   - `gir_agent/agent.py` (see `root_agent` around line 13)
   - Defines the root `LlmAgent`
   - Wraps two specialist sub-agents as tools

2. **Orchestration policy**
   - `gir_agent/prompt.py` (around line 3)
   - Enforces a workflow:
     1) extract locations  
     2) enrich with web search  
     3) geocode with OSM  
     4) generate a top-3 report

3. **Sub-agents**
   - **Search sub-agent**
     - `gir_agent/sub_agents/google_search_agent.py` (around line 42)
     - Uses ADK `google_search` with strict structured output
   - **OSM sub-agent**
     - `gir_agent/sub_agents/osm_agent.py` (around line 6)
     - Uses local tools: `geo_coding` and `visualize_geojson`

---

## Geo Tools

- **Geocoding**
  - `gir_agent/tools/geo_tools.py` (around line 27)
  - Calls `geopy.Nominatim`
  - Converts results into GeoJSON features
  - Stores GeoJSON in session state at: `user:geo_json`

- **Visualization**
  - `gir_agent/tools/visualize_tool.py` (around line 59)
  - Reads GeoJSON from tool context
  - Renders a Folium map to HTML
  - Writes files like: `maps/geo_map_*.html`
  - Saves artifact metadata in state: `user:last_geo_map_path`

---

## Interfaces

### 1) CLI Chat

- `gir_agent/chat_interface.py` (around line 21)
- Runs a single ADK session loop in the terminal

**Example**
```bash
python3 -m gir_agent.chat_interface
```

### 2) Batch CSV Runner

- `gir_agent/csv_runner.py`
- Runs one fresh ADK session per CSV row and writes the agent response to a new CSV

**Expected input columns**
```text
id,query
```

Any extra columns, such as `groundtruth_output`, are preserved in the output.

**Example**
```bash
python3 -m gir_agent.csv_runner --input-csv sample_batch_input.csv --output-csv batch_output.csv
```

**Output columns**
```text
<all input columns>,agent_output,status,error_message
```
