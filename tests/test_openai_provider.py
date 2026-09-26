"""OpenAIProvider through the real ``openai`` SDK, with HTTP served by an
in-process fake (httpx.MockTransport). Exercises request serialization,
function-calling round-trips, structured outputs and tool-result history."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest

from autotool.core.llm import OpenAIProvider
from autotool.core.orchestrator import SYNTHESIZE_TOOL, Orchestrator
from autotool.core.registry import ToolRegistry
from autotool.synthesis.repair import SynthesisEngine
from autotool.synthesis.verifier import ToolVerifier
from tests.test_synthesis import GOOD


def completion(message: dict[str, Any], finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test",
        "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish_reason}],
    }


def tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeOpenAI:
    """Minimal stateful stand-in for the Chat Completions endpoint."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        assert request.url.path.endswith("/chat/completions")
        assert body["messages"][0]["role"] == "system"

        if "response_format" in body:  # structured output: the tool generator
            schema = body["response_format"]["json_schema"]
            assert schema["strict"] is True and schema["name"] == "GeneratedToolCandidate"
            payload = {"code": GOOD, "primary_tool": "add", "smoke_test_arguments_json": '{"a": 1, "b": 2}'}
            return httpx.Response(200, json=completion({"content": json.dumps(payload)}))

        tool_names = {t["function"]["name"] for t in body.get("tools", [])}
        last = body["messages"][-1]
        if last["role"] == "user":
            assert tool_names == {SYNTHESIZE_TOOL}
            call = tool_call("call_s", SYNTHESIZE_TOOL, {"tool_name": "math_tool", "capability_description": "Add ints"})
            return httpx.Response(200, json=completion({"content": None, "tool_calls": [call]}, "tool_calls"))
        if last["role"] == "tool" and last["tool_call_id"] == "call_s":
            assert "math_tool__add" in tool_names  # hot-loaded before the next request
            call = tool_call("call_a", "math_tool__add", {"a": 20, "b": 22})
            return httpx.Response(200, json=completion({"content": None, "tool_calls": [call]}, "tool_calls"))
        if last["role"] == "tool" and last["tool_call_id"] == "call_a":
            # The assistant tool_calls turn preceding it must be replayed intact.
            assert body["messages"][-2]["tool_calls"][0]["id"] == "call_a"
            return httpx.Response(200, json=completion({"content": f"The answer is {last['content']}."}))
        raise AssertionError(f"unexpected request: {body['messages']}")


@pytest.fixture
def fake() -> FakeOpenAI:
    return FakeOpenAI()


@pytest.fixture
def provider(fake: FakeOpenAI) -> OpenAIProvider:
    client = openai.AsyncOpenAI(
        api_key="test", base_url="https://fake.openai.test/v1", http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )
    return OpenAIProvider("gpt-test", client=client)


async def test_openai_end_to_end_synthesis(provider, fake, tmp_path):
    tools_dir = tmp_path / "tools"
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=ToolVerifier(tmp_path / "stg"))
    async with ToolRegistry(tools_dir) as registry:
        run = await Orchestrator(provider, registry, engine).run("What is 20 + 22?")

    assert run.answer == "The answer is 42."
    assert run.synthesized == ["math_tool"]
    assert (tools_dir / "math_tool.py").read_text() == GOOD
    assert len(fake.requests) == 4  # chat, generate (structured), chat, chat


async def test_openai_tool_error_is_marked(provider):
    from autotool.core.schema import ToolResult

    (msg,) = provider.tool_results_messages([ToolResult(call_id="x", content="boom", is_error=True)])
    assert msg == {"role": "tool", "tool_call_id": "x", "content": "ERROR: boom"}
