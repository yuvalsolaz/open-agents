from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from gir_agent.tools import geo_coding
from config import LLM_MODEL

osm_agent = Agent(
    name="osm_agent",
    model=LiteLlm(model=LLM_MODEL),
    description="An osm based geo coding expert using geopy tools.",
    tools=[geo_coding]
)