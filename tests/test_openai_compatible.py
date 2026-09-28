"""OpenAI-compatible endpoints (Ollama, LM Studio, vLLM, OpenRouter): Chat Completions over any base_url,
served here by an in-process fake so no server or key is needed."""

from __future__ import annotations

import json
from typing import Any

import httpx
import openai
import pytest

import autotool
from autotool.core.llm import OpenAICompatibleProvider, OpenAIProvider, default_provider
from autotool.core.schema import GeneratedToolCandidate
from tests.test_synthesis import GOOD


def chat_response(message: dict[str, Any]) -> dict[str, Any]:
    return {"id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "local-model",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def tool_call(call_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeCompatibleServer:
    """Speaks /v1/chat/completions only, like Ollama; rejects json_schema response formats."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions"), request.url
        body = json.loads(request.content)
        self.requests.append(body)
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        messages = body["messages"]
        assert messages[0]["role"] == "system"
        if "tools" not in body:  # structured output, second try without response_format
            payload = {"code": GOOD, "primary_tool": "add", "smoke_test_arguments_json": '{"a": 1, "b": 2}'}
            return httpx.Response(200, json=chat_response({"role": "assistant", "content": "```json\n" + json.dumps(payload) + "\n```"}))
        assert all(t["type"] == "function" and "parameters" in t["function"] for t in body["tools"])
        last = messages[-1]
        if last["role"] == "user":
            return httpx.Response(200, json=chat_response({"role": "assistant", "content": None, "tool_calls": [
                tool_call("c1", "create_tool", {"name": "math_tool", "code": GOOD, "test_arguments": {"a": 1, "b": 2}})]}))
        if last["role"] == "tool" and last["tool_call_id"] == "c1":
            assert messages[-2]["tool_calls"][0]["id"] == "c1"  # the assistant turn is replayed intact
            return httpx.Response(200, json=chat_response({"role": "assistant", "content": None, "tool_calls": [
                tool_call("c2", "run_tool", {"name": "math_tool__add", "arguments": {"a": 20, "b": 22}})]}))
        if last["role"] == "tool" and last["tool_call_id"] == "c2":
            return httpx.Response(200, json=chat_response({"role": "assistant", "content": f"The answer is {last['content']}."}))
        raise AssertionError(f"unexpected request: {messages}")


@pytest.fixture
def fake() -> FakeCompatibleServer:
    return FakeCompatibleServer()


@pytest.fixture
def provider(fake: FakeCompatibleServer) -> OpenAICompatibleProvider:
    client = openai.AsyncOpenAI(api_key="not-needed", base_url="http://localhost:11434/v1",
                                http_client=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    return OpenAICompatibleProvider("local-model", client=client)


async def test_run_agent_on_an_openai_compatible_endpoint(provider, fake, tmp_path):
    answer = await autotool.run_agent("What is 20 + 22?", provider, home=tmp_path / "home")
    assert answer == "The answer is 42."
    assert provider.usage.calls == 3


async def test_structured_output_falls_back_when_json_schema_is_unsupported(provider, fake):
    candidate = await provider.structured(system="Write a tool.", prompt="add ints", output_model=GeneratedToolCandidate)
    assert candidate.primary_tool == "add" and "FastMCP" in candidate.code
    assert [r.get("response_format", {}).get("type") for r in fake.requests] == ["json_schema", None]


def test_base_url_selects_the_compatible_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("OPENAI_LLM", "qwen2.5:14b")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AUTOTOOL_PROVIDER", raising=False)
    provider = default_provider()
    assert isinstance(provider, OpenAICompatibleProvider) and provider.model == "qwen2.5:14b"
    assert str(provider.client.base_url).startswith("http://localhost:11434/v1")
    monkeypatch.setenv("AUTOTOOL_PROVIDER", "openai")  # explicit choice keeps the Responses API
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert isinstance(default_provider(), OpenAIProvider)


def test_compatible_provider_needs_a_model_name(monkeypatch):
    monkeypatch.delenv("OPENAI_LLM", raising=False)
    monkeypatch.delenv("AUTOTOOL_OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError, match="OPENAI_LLM"):
        OpenAICompatibleProvider(base_url="http://localhost:11434/v1")


def test_synthesis_can_use_a_local_endpoint_without_a_key(tmp_path, monkeypatch):
    from autotool.server import model_provider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_BASE_URL=http://localhost:11434/v1\nOPENAI_LLM=gemma4:12b\n")
    provider = model_provider(tmp_path)
    assert isinstance(provider, OpenAICompatibleProvider) and provider.model == "gemma4:12b"
    assert str(provider.client.base_url).startswith("http://localhost:11434/v1")
