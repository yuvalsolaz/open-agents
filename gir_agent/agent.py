# gir_agent/agent.py
from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
# Import the sub-agent INSTANCES
from .sub_agents.google_search_agent import google_search_agent
from .sub_agents.osm_agent import osm_agent
from . import prompt
from config import LLM_MODEL

# This is our main "manager" agent, now an LlmAgent
root_agent = LlmAgent(
        model=LLM_MODEL,
        name="GIROrchestrator",
        description="The manager of a team of specialist AI agents.",
        instruction=prompt.ORCHESTRATOR_PROMPT,
        # The Orchestrator's "tools" are its sub-agents, wrapped in AgentTool
        tools=[AgentTool(agent=google_search_agent), AgentTool(agent=osm_agent)
],
)