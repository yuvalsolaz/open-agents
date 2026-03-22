from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from gir_agent.tools import (
    geo_coding,
    rerank_candidates,
    reverse_geocoding,
    visualize_geojson,
)
from gir_agent.config import LLM_MODEL

OSM_AGENT_PROMPT = """
You are a geographic candidate analysis specialist.

When you generate multiple location candidates from geocoding or nearby-place lookup:
- compare them against the user's original query
- use `rerank_candidates` before deciding which candidates to return
- prefer candidates whose names, place types, and nearby context best match the query
- keep the top-ranked candidates and explain the match clearly

If geocoding produces GeoJSON, call `visualize_geojson`.
If you have coordinates and need nearby evidence, call `reverse_geocoding`.
"""

osm_agent = Agent(
    name="osm_agent",
    model=LiteLlm(model=LLM_MODEL),
    description=(
        "A geo coding and reverse-geocoding expert using OSM and Google Places. "
        "Always visualize geocoding results into an interactive map."
    ),
    instruction=OSM_AGENT_PROMPT,
    tools=[geo_coding, reverse_geocoding, rerank_candidates, visualize_geojson],
)
