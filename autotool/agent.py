"""Build with AutoTool from Python.

    import asyncio, autotool
    from autotool.core.llm import default_provider          # needs autotool-mcp[models] + OPENAI_API_KEY

    print(asyncio.run(autotool.run_agent("What's the top story on Hacker News?", default_provider())))

Or bring your own agent loop:

    async with autotool.connect() as session:                # AutoTool running as an MCP server
        tools = autotool.openai_tools(await session.list_tools())   # or anthropic_tools(...)
        result = await session.call_tool(name, arguments)    # whatever your model asks for
"""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters, types

from autotool.core.llm import LLMProvider
from autotool.core.schema import ToolResult

SYSTEM = (
    "You are a helpful agent. Use your tools for anything that needs live data or an external API. "
    "If no tool fits, write one with create_tool, then call it. Never invent data a tool should provide."
)


@asynccontextmanager
async def connect(
    home: str | Path | None = None,
    env: dict[str, str] | None = None,
    on_consent: Callable[[str], bool] | None = None,
    server: StdioServerParameters | None = None,
) -> AsyncIterator[Client]:
    """Start `autotool serve` as a subprocess and yield a connected MCP client.

    home: AutoTool's data directory (default ~/.autotool). env: extra environment for the
    server, e.g. {"AUTOTOOL_KEY_TAVILY_API_KEY": "..."}. on_consent: shown AutoTool's approval
    question ("allow tool X to use KEY?"), returns the user's answer; without it, credentialed
    tools need `autotool tools approve`. server: launch parameters to use instead."""
    if server is None:
        server_env = {**os.environ, **(env or {})}
        if home is not None:
            server_env["AUTOTOOL_HOME"] = str(home)
        server = StdioServerParameters(command=sys.executable, args=["-m", "autotool", "serve"], env=server_env)

    async def elicit(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        return types.ElicitResult(action="accept", content={"allow": bool(on_consent and on_consent(params.message))})

    async with Client(server, elicitation_callback=elicit if on_consent else None) as client:
        yield client


def openai_tools(listed: types.ListToolsResult) -> list[dict[str, Any]]:
    """Tool schemas for the OpenAI Responses API (`tools=`)."""
    return [
        {"type": "function", "name": t.name, "description": t.description or "", "parameters": t.input_schema}
        for t in listed.tools
    ]


def anthropic_tools(listed: types.ListToolsResult) -> list[dict[str, Any]]:
    """Tool schemas for the Anthropic Messages API (`tools=`)."""
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in listed.tools]


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


async def run_agent(
    prompt: str,
    provider: LLMProvider,
    *,
    home: str | Path | None = None,
    env: dict[str, str] | None = None,
    on_consent: Callable[[str], bool] | None = None,
    on_tool: Callable[[str, dict[str, Any], types.CallToolResult], None] | None = None,
    server: StdioServerParameters | None = None,
    max_steps: int = 15,
) -> str:
    """A complete agent: the model sees AutoTool's tools, writes new ones when it needs them, and
    answers. Tools are listed every turn, so a tool created in one step is usable in the next."""
    async with connect(home, env, on_consent, server) as session:
        messages: list[Any] = [{"role": "user", "content": prompt}]
        for _ in range(max_steps):
            tools = anthropic_tools(await session.list_tools())  # the providers' neutral shape
            turn = await provider.complete(system=SYSTEM, messages=messages, tools=tools)
            messages.append(provider.assistant_message(turn))
            if not turn.tool_calls:
                return turn.text
            results = []
            for call in turn.tool_calls:
                result = await session.call_tool(call.name, call.arguments)
                if on_tool:
                    on_tool(call.name, call.arguments, result)
                results.append(ToolResult(call_id=call.id, content=_text(result), is_error=bool(result.is_error)))
            messages.extend(provider.tool_results_messages(results))
        raise RuntimeError(f"no answer within {max_steps} steps")
