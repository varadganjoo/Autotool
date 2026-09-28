"""The Python entry points a developer uses right after `pip install autotool-mcp`."""

from __future__ import annotations

import autotool
from autotool.core.llm import ScriptedProvider
from autotool.core.schema import LLMTurn, ToolCall
from tests.test_synthesis import GOOD


async def test_connect_gives_a_ready_session_and_provider_ready_tool_schemas(tmp_path):
    async with autotool.connect(home=tmp_path / "home") as session:
        created = await session.call_tool("create_tool", {"name": "math_tool", "code": GOOD, "test_arguments": {"a": 1, "b": 2}})
        assert not created.isError
        listed = await session.list_tools()
        openai_tools = autotool.openai_tools(listed)
        anthropic_tools = autotool.anthropic_tools(listed)
    assert {"type": "function", "name": "math_tool__add"} == {k: v for k, v in openai_tools[-1].items() if k in ("type", "name")}
    assert anthropic_tools[-1]["name"] == "math_tool__add" and "input_schema" in anthropic_tools[-1]


async def test_run_agent_builds_a_tool_and_answers(tmp_path):
    turns = 0

    def chat(messages, tools):
        nonlocal turns
        turns += 1
        if turns == 1:
            assert "create_tool" in {t["name"] for t in tools}
            return LLMTurn(tool_calls=[ToolCall(id="c1", name="create_tool", arguments={
                "name": "math_tool", "code": GOOD, "test_arguments": {"a": 1, "b": 2}})])
        if turns == 2:
            return LLMTurn(tool_calls=[ToolCall(id="c2", name="run_tool", arguments={
                "name": "math_tool__add", "arguments": {"a": 20, "b": 22}})])
        return LLMTurn(text="The answer is " + messages[-1]["content"][0]["content"])

    provider = ScriptedProvider(chat, lambda prompt, model: None)
    answer = await autotool.run_agent("What is 20 + 22?", provider, home=tmp_path / "home")
    assert answer == "The answer is 42"
