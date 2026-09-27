"""A minimal agent of your own, connected to AutoTool over MCP.

Any MCP client works the same way: start `autotool serve` over stdio, list tools every turn
(new ones appear after create_tool), and pass tool calls through.

    pip install "autotool-mcp[models]"   # this example's own model client (OpenAI or Anthropic)
    python examples/mcp_agent.py "What is the current top story on Hacker News?"
"""

from __future__ import annotations

import sys
from typing import Any, Callable

import anyio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from autotool.core.llm import LLMProvider, default_provider
from autotool.core.schema import ToolResult

SYSTEM = (
    "You are a helpful agent. Use your tools for anything that needs live data or an external API. "
    "If no tool fits, write one with create_tool, then call it. Never invent data a tool should provide."
)


def _text(result: types.CallToolResult) -> str:
    return "\n".join(c.text for c in result.content if isinstance(c, types.TextContent))


async def run_agent(
    prompt: str,
    provider: LLMProvider,
    server: StdioServerParameters | None = None,
    max_steps: int = 15,
    on_tool: Callable[[str, dict[str, Any], types.CallToolResult], None] | None = None,
    on_consent: Callable[[str], bool] | None = None,
) -> str:
    """on_consent: shown AutoTool's approval question ("allow tool X to use KEY?"), returns the
    user's answer. Without it, AutoTool tells the agent to ask for `autotool tools approve`."""
    server = server or StdioServerParameters(command=sys.executable, args=["-m", "autotool", "serve"])

    async def elicit(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
        return types.ElicitResult(action="accept", content={"allow": bool(on_consent and on_consent(params.message))})

    async with stdio_client(server) as (read, write), ClientSession(
        read, write, elicitation_callback=elicit if on_consent else None
    ) as session:
        await session.initialize()
        messages: list[Any] = [{"role": "user", "content": prompt}]
        for _ in range(max_steps):
            listed = await session.list_tools()
            tools = [{"name": t.name, "description": t.description or "", "input_schema": t.inputSchema} for t in listed.tools]
            turn = await provider.complete(system=SYSTEM, messages=messages, tools=tools)
            messages.append(provider.assistant_message(turn))
            if not turn.tool_calls:
                return turn.text
            results = []
            for call in turn.tool_calls:
                result = await session.call_tool(call.name, call.arguments)
                if on_tool:
                    on_tool(call.name, call.arguments, result)
                results.append(ToolResult(call_id=call.id, content=_text(result), is_error=bool(result.isError)))
            messages.extend(provider.tool_results_messages(results))
        raise RuntimeError(f"no answer within {max_steps} steps")


if __name__ == "__main__":
    print(anyio.run(run_agent, sys.argv[1], default_provider()))
