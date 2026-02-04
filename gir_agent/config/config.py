
import os
from dotenv import load_dotenv

load_dotenv()

# Access OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE", "0.0")


