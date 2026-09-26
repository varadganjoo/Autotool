"""LLM provider abstraction.

``AnthropicProvider`` is the production backend (Claude via the official
``anthropic`` SDK). ``ScriptedProvider`` replays deterministic responses and
is used for offline demos and tests. Conversation history is kept in the
Anthropic Messages format for both.
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Protocol, TypeVar

from pydantic import BaseModel

from autotool.core.schema import LLMTurn, ToolCall, ToolResult

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"
# Server-side refusal fallbacks: on a policy decline the API re-runs the
# request on a fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMRefusalError(RuntimeError):
    pass


class LLMProvider(Protocol):
    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn: ...

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T: ...

    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]: ...

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]: ...


class _AnthropicFormatMixin:
    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]:
        return {"role": "assistant", "content": turn.raw_content}

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]:
        # All results for one assistant turn go back in a single user message.
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                for r in results
            ],
        }


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
        if response.stop_reason == "refusal":
            raise LLMRefusalError(f"Model declined the request: {response.stop_details}")
        if response.parsed_output is None:
            raise RuntimeError(f"No structured output returned (stop_reason={response.stop_reason})")
        return response.parsed_output


ChatHandler = Callable[[list[dict[str, Any]], list[dict[str, Any]]], Awaitable[LLMTurn] | LLMTurn]
StructuredHandler = Callable[[str, type[BaseModel]], Awaitable[BaseModel] | BaseModel]


class ScriptedProvider(_AnthropicFormatMixin):
    """Deterministic provider driven by callables. ``chat`` receives
    ``(messages, tools)``; ``structured`` receives ``(prompt, output_model)``."""

    def __init__(self, chat: ChatHandler, structured: StructuredHandler) -> None:
        self._chat = chat
        self._structured = structured

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
