"""LLM provider abstraction.

``OpenAIProvider`` (Chat Completions) and ``AnthropicProvider`` (Claude) are the
production backends. ``ScriptedProvider`` replays deterministic responses for
offline demos and tests. The orchestrator passes tool definitions in a neutral
``{name, description, input_schema}`` shape; each provider owns its own
message-history format via ``assistant_message`` / ``tool_results_messages``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from pydantic import BaseModel

from autotool.core.schema import LLMTurn, ToolCall, ToolResult

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_OPENAI_MODEL = "gpt-5"
# Server-side refusal fallbacks: on a policy decline the API re-runs the
# request on a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMRefusalError(RuntimeError):
    pass


class UsageStats(BaseModel):
    """Cumulative token usage across every request a provider made."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.calls += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0


class LLMProvider(Protocol):
    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn: ...

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T: ...

    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]: ...

    def tool_results_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]: ...


class _AnthropicFormatMixin:
    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]:
        return {"role": "assistant", "content": turn.raw_content}

    def tool_results_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        # All results for one assistant turn go back in a single user message.
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                    for r in results
                ],
            }
        ]


class AnthropicProvider(_AnthropicFormatMixin):
    def __init__(
        self,
        model: str | None = None,
        *,
        max_tokens: int = 16000,
        use_fallbacks: bool = True,
        client: Any = None,
    ) -> None:
        import anthropic

        self.model = model or os.environ.get("AUTOTOOL_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks
        self.client = client or anthropic.AsyncAnthropic()
        self.usage = UsageStats()

    def _record(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        self.usage.add(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))

    def _extra(self) -> dict[str, Any]:
        if not self.use_fallbacks:
            return {}
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        response = await self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            **self._extra(),
        )
        self._record(response)
        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"Model declined the request: {response.stop_details}")
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in response.content
            if b.type == "tool_use"
        ]
        if response.stop_reason == "max_tokens" and calls:
            raise RuntimeError("Response hit max_tokens mid tool call; tool input may be truncated")
        return LLMTurn(text=text, tool_calls=calls, stop_reason=response.stop_reason, raw_content=response.content)

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        response = await self.client.beta.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_model,
            **self._extra(),
        )
        self._record(response)
        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"Model declined the request: {response.stop_details}")
        if response.parsed_output is None:
            raise RuntimeError(f"No structured output returned (stop_reason={response.stop_reason})")
        return response.parsed_output


class OpenAIProvider:
    """OpenAI Chat Completions backend (function calling + structured outputs)."""

    def __init__(self, model: str | None = None, *, client: Any = None, reasoning_effort: str | None = None) -> None:
        import openai

        self.model = (
            model or os.environ.get("AUTOTOOL_OPENAI_MODEL") or os.environ.get("OPENAI_LLM") or DEFAULT_OPENAI_MODEL
        )
        self.reasoning_effort = reasoning_effort
        self.client = client or openai.AsyncOpenAI()
        self.usage = UsageStats()

    def _record(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        self.usage.add(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))

    def _extra(self) -> dict[str, Any]:
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]},
            }
            for t in tools
        ]

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            tools=self._tools(tools) or None,
            **self._extra(),
        )
        self._record(response)
        choice = response.choices[0]
        msg = choice.message
        if getattr(msg, "refusal", None):
            raise LLMRefusalError(f"Model declined the request: {msg.refusal}")
        if choice.finish_reason == "length" and msg.tool_calls:
            raise RuntimeError("Response hit the token limit mid tool call; arguments may be truncated")
        calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            if tc.type != "function":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args if isinstance(args, dict) else {}))
        return LLMTurn(
            text=msg.content or "",
            tool_calls=calls,
            stop_reason=choice.finish_reason,
            raw_content=msg.model_dump(exclude_none=True, exclude_unset=True),
        )

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        response = await self.client.chat.completions.parse(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format=output_model,
            **self._extra(),
        )
        self._record(response)
        msg = response.choices[0].message
        if msg.refusal:
            raise LLMRefusalError(f"Model declined the request: {msg.refusal}")
        if msg.parsed is None:
            raise RuntimeError(f"No structured output returned (finish_reason={response.choices[0].finish_reason})")
        return msg.parsed

    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]:
        message = dict(turn.raw_content or {"role": "assistant", "content": turn.text})
        message["role"] = "assistant"
        return message

    def tool_results_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        # Chat Completions has no is_error flag; mark failures in the content.
        return [
            {"role": "tool", "tool_call_id": r.call_id, "content": f"ERROR: {r.content}" if r.is_error else r.content}
            for r in results
        ]


def default_provider(name: str | None = None, model: str | None = None, **kwargs: Any) -> LLMProvider:
    """``name`` is 'openai' or 'anthropic'; when omitted, pick OpenAI if
    OPENAI_API_KEY is set, else Anthropic."""
    name = (name or os.environ.get("AUTOTOOL_PROVIDER") or ("openai" if os.environ.get("OPENAI_API_KEY") else "anthropic")).lower()
    if name == "openai":
        return OpenAIProvider(model, reasoning_effort=kwargs.get("reasoning_effort"))
    if name == "anthropic":
        return AnthropicProvider(model, use_fallbacks=kwargs.get("use_fallbacks", True))
    raise ValueError(f"Unknown provider {name!r}; expected 'openai' or 'anthropic'")


ChatHandler = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[LLMTurn] | LLMTurn]
StructuredHandler = Callable[[str, type[BaseModel]], Awaitable[BaseModel] | BaseModel]


class ScriptedProvider(_AnthropicFormatMixin):
    """Deterministic provider driven by callables. ``chat`` receives
    ``(messages, tools)``; ``structured`` receives ``(prompt, output_model)``."""

    def __init__(self, chat: ChatHandler, structured: StructuredHandler) -> None:
        self._chat = chat
        self._structured = structured
        self.model = "scripted"
        self.usage = UsageStats()

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        turn = self._chat(messages, tools)
        turn = await turn if isinstance(turn, Awaitable) else turn
        if turn.raw_content is None:
            content: list[dict[str, Any]] = []
            if turn.text:
                content.append({"type": "text", "text": turn.text})
            content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in turn.tool_calls]
            turn.raw_content = content
        return turn

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        out = self._structured(prompt, output_model)
        out = await out if isinstance(out, Awaitable) else out
        return output_model.model_validate(out.model_dump() if isinstance(out, BaseModel) else out)
