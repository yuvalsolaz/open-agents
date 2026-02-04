from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from gir_agent.tools import geo_coding, visualize_geojson
from gir_agent.config import LLM_MODEL

osm_agent = Agent(
    name="osm_agent",
    model=LiteLlm(model=LLM_MODEL),
    description=(
        "An OSM-based geo coding expert using geopy tools. "
        "Always visualize results into an interactive map after geocoding."
    ),
    tools=[geo_coding, visualize_geojson],
)
