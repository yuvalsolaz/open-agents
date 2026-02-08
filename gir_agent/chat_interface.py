import asyncio

from google.genai import types
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.sessions.in_memory_session_service import InMemorySessionService

from gir_agent.agent import root_agent

APP_NAME = "gir_agent"
USER_ID = "local_user"


def _extract_text(event) -> str:
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts)


async def run_chat() -> None:
    artifact_service = InMemoryArtifactService()
    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        artifact_service=artifact_service,
        session_service=session_service,
    )

    print("Gir Agent chat. Type 'exit' or 'quit' to leave.")
    while True:
        try:
            query = input("[user]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            break

        async for event in runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=query)]),
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            text = _extract_text(event)
            if text:
                print(f"[{event.author}]: {text}")

    await runner.close()


if __name__ == "__main__":
    asyncio.run(run_chat())
