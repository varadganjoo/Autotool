"""A complete agent of your own on top of AutoTool, in a few lines.

    pip install "autotool-mcp[models]"        # this example's model client (OpenAI or Anthropic)
    export OPENAI_API_KEY=...                  # or ANTHROPIC_API_KEY
    python examples/mcp_agent.py "What is the current top story on Hacker News?"

autotool.run_agent lists AutoTool's tools every turn, lets the model write new ones with
create_tool, and asks you before any tool gets one of your credentials.
"""

import asyncio
import sys

import autotool
from autotool.core.llm import default_provider


def ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() == "y"


if __name__ == "__main__":
    print(asyncio.run(autotool.run_agent(sys.argv[1], default_provider(), on_consent=ask)))
