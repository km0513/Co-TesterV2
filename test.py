import os
os.environ["PLAYWRIGHT_HEADLESS"] = "true"  # Set this first!

from dotenv import load_dotenv
load_dotenv()

from browser_use import Agent
from langchain_openai import ChatOpenAI
import asyncio

async def main():
    agent = Agent(
        task="Go to https://example.com and take a screenshot.",
        llm=ChatOpenAI(model="gpt-4o"),
    )
    await agent.run()

asyncio.run(main())