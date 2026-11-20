import asyncio
import sys
import traceback

sys.path.insert(0, "N:/WorkBuddy/2026-05-29-01-14-11/ai-agent-os/backend")

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database import engine, async_session_factory
from app.services.agent_executor import AgentExecutor


async def test_execute():
    async with async_session_factory() as db:
        executor = AgentExecutor(db)
        try:
            # Use the task ID that was created earlier
            result = await executor.execute(
                "5db00acc-318d-4156-965c-17663fae2b06",
                "a0f674f2-f9d7-4d9f-914b-05e7e295a0b2",
            )
            print("Result:", result)
        except Exception as e:
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_execute())
