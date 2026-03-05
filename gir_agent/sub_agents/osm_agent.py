from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from gir_agent.tools import geo_coding, reverse_geocoding, visualize_geojson
from gir_agent.config import LLM_MODEL

osm_agent = Agent(
    name="osm_agent",
    model=LiteLlm(model=LLM_MODEL),
    description=(
        "A geo coding and reverse-geocoding expert using OSM and Google Places. "
        "Always visualize geocoding results into an interactive map."
    ),
    tools=[geo_coding, reverse_geocoding, visualize_geojson],
)
