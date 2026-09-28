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
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from autotool.core.schema import LLMTurn, ToolCall, ToolResult

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_OPENAI_MODEL = "gpt-6-sol"  # OpenAI's tier for coding and agentic work; gpt-6-astra is the premium one
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
        calls = [ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {})) for b in response.content if b.type == "tool_use"]
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
    """OpenAI Responses API backend (function calling + structured outputs)."""

    def __init__(self, model: str | None = None, *, client: Any = None, reasoning_effort: str | None = None) -> None:
        import openai

        self.model = model or os.environ.get("AUTOTOOL_OPENAI_MODEL") or os.environ.get("OPENAI_LLM") or DEFAULT_OPENAI_MODEL
        self.reasoning_effort = reasoning_effort
        self.client = client or openai.AsyncOpenAI()
        self.usage = UsageStats()

    def _record(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        in_tok = getattr(u, "input_tokens", None) or getattr(u, "prompt_tokens", 0)
        out_tok = getattr(u, "output_tokens", None) or getattr(u, "completion_tokens", 0)
        self.usage.add(in_tok, out_tok)

    def _extra(self) -> dict[str, Any]:
        return {"reasoning": {"effort": self.reasoning_effort}} if self.reasoning_effort else {}

    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        res_tools = []
        for t in tools:
            if "function" in t:
                f = t["function"]
                res_tools.append(
                    {
                        "type": "function",
                        "name": f["name"],
                        "description": f.get("description", ""),
                        "parameters": f.get("parameters", {}),
                    }
                )
            else:
                res_tools.append(
                    {
                        "type": "function",
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema") or t.get("parameters") or {},
                    }
                )
        return res_tools

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        input_items: list[Any] = []
        for m in messages:
            if isinstance(m, list):
                input_items.extend(m)
            else:
                input_items.append(m)

        tools_param = self._tools(tools)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": input_items,
            **self._extra(),
        }
        if tools_param:
            kwargs["tools"] = tools_param

        response = await self.client.responses.create(**kwargs)
        self._record(response)

        if getattr(response, "error", None):
            raise RuntimeError(f"Model response error: {response.error}")

        text_chunks: list[str] = []
        calls: list[ToolCall] = []

        for item in getattr(response, "output", []):
            item_type = getattr(item, "type", None) or (item.get("type") if isinstance(item, dict) else None)
            if item_type == "message":
                contents = getattr(item, "content", []) or (item.get("content", []) if isinstance(item, dict) else [])
                for part in contents:
                    part_type = getattr(part, "type", None) or (part.get("type") if isinstance(part, dict) else None)
                    if part_type == "output_text":
                        text_chunks.append(getattr(part, "text", "") or (part.get("text", "") if isinstance(part, dict) else ""))
            elif item_type == "function_call":
                call_id = (
                    getattr(item, "call_id", None)
                    or (item.get("call_id") if isinstance(item, dict) else None)
                    or getattr(item, "id", "")
                )
                name = getattr(item, "name", "") or (item.get("name", "") if isinstance(item, dict) else "")
                args_raw = getattr(item, "arguments", "{}") or (item.get("arguments", "{}") if isinstance(item, dict) else "{}")
                if isinstance(args_raw, dict):
                    args = args_raw
                else:
                    try:
                        args = json.loads(args_raw or "{}")
                    except json.JSONDecodeError:
                        args = {"__invalid_json__": args_raw}
                calls.append(ToolCall(id=call_id, name=name, arguments=args if isinstance(args, dict) else {}))

        text = "".join(text_chunks)
        if not text and hasattr(response, "output_text") and response.output_text:
            text = response.output_text

        raw_items = []
        for item in getattr(response, "output", []):
            if hasattr(item, "model_dump"):
                raw_items.append(item.model_dump(exclude_none=True))
            elif isinstance(item, dict):
                raw_items.append(item)

        return LLMTurn(
            text=text,
            tool_calls=calls,
            stop_reason=getattr(response, "status", None),
            raw_content=raw_items,
        )

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        response = await self.client.responses.parse(
            model=self.model,
            instructions=system,
            input=prompt,
            text_format=output_model,
            **self._extra(),
        )
        self._record(response)
        if getattr(response, "error", None):
            raise RuntimeError(f"Model response error: {response.error}")
        if getattr(response, "output_parsed", None) is None:
            raise RuntimeError(f"No structured output returned (status={getattr(response, 'status', None)})")
        return response.output_parsed

    def assistant_message(self, turn: LLMTurn) -> Any:
        return turn.raw_content if turn.raw_content else [{"role": "assistant", "content": turn.text}]

    def tool_results_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function_call_output",
                "call_id": r.call_id,
                "output": f"ERROR: {r.content}" if r.is_error else r.content,
            }
            for r in results
        ]


def _json_object(text: str) -> str:
    """The JSON object in a model reply that may wrap it in prose or ``` fences."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


class OpenAICompatibleProvider:
    """Chat Completions backend for any OpenAI-compatible server: Ollama, LM Studio, vLLM,
    OpenRouter, ... (most of them do not implement the Responses API that OpenAIProvider uses).

    base_url / api_key / model default to OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_LLM; local
    servers usually need no key."""

    def __init__(
        self, model: str | None = None, *, base_url: str | None = None, api_key: str | None = None, client: Any = None
    ) -> None:
        import openai

        self.model = model or os.environ.get("AUTOTOOL_OPENAI_MODEL") or os.environ.get("OPENAI_LLM")
        if not self.model:
            raise ValueError(
                "Name the model to use on your OpenAI-compatible endpoint: set OPENAI_LLM "
                "(e.g. OPENAI_LLM=qwen2.5:14b for Ollama) or pass model=..."
            )
        self.client = client or openai.AsyncOpenAI(
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
            api_key=api_key or os.environ.get("OPENAI_API_KEY") or "not-needed",  # local servers ignore it
        )
        self.usage = UsageStats()

    def _record(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        self.usage.add(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        kwargs: dict[str, Any] = {"model": self.model, "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                    },
                }
                for t in tools
            ]
        response = await self.client.chat.completions.create(**kwargs)
        self._record(response)
        message = response.choices[0].message
        raw: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        calls: list[ToolCall] = []
        for i, c in enumerate(message.tool_calls or []):
            call_id = c.id or f"call_{i}"
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"__invalid_json__": c.function.arguments}
            calls.append(ToolCall(id=call_id, name=c.function.name, arguments=args if isinstance(args, dict) else {}))
            raw.setdefault("tool_calls", []).append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
                }
            )
        return LLMTurn(
            text=message.content or "", tool_calls=calls, stop_reason=response.choices[0].finish_reason, raw_content=raw
        )

    async def structured(self, *, system: str, prompt: str, output_model: type[T]) -> T:
        import openai

        schema = output_model.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": f"{system}\n\nReply with only a JSON object matching this JSON schema:\n{json.dumps(schema)}",
            },
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": {"name": output_model.__name__, "schema": schema}},
            )
        except openai.BadRequestError:  # servers without JSON-schema output: the schema is in the prompt
            response = await self.client.chat.completions.create(model=self.model, messages=messages)
        self._record(response)
        return output_model.model_validate_json(_json_object(response.choices[0].message.content or ""))

    def assistant_message(self, turn: LLMTurn) -> dict[str, Any]:
        return turn.raw_content

    def tool_results_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        return [
            {"role": "tool", "tool_call_id": r.call_id, "content": f"ERROR: {r.content}" if r.is_error else r.content}
            for r in results
        ]


def default_provider(name: str | None = None, model: str | None = None, **kwargs: Any) -> LLMProvider:
    """``name`` is 'openai', 'openai-compatible' or 'anthropic' (or $AUTOTOOL_PROVIDER). When omitted:
    an OpenAI-compatible endpoint if OPENAI_BASE_URL is set (Ollama, LM Studio, vLLM, OpenRouter...),
    else OpenAI if OPENAI_API_KEY is set, else Anthropic."""
    name = (
        name
        or os.environ.get("AUTOTOOL_PROVIDER")
        or (
            "openai-compatible"
            if os.environ.get("OPENAI_BASE_URL")
            else "openai"
            if os.environ.get("OPENAI_API_KEY")
            else "anthropic"
        )
    ).lower()
    if name == "openai-compatible":
        return OpenAICompatibleProvider(model)
    if name == "openai":
        return OpenAIProvider(model, reasoning_effort=kwargs.get("reasoning_effort"))
    if name == "anthropic":
        return AnthropicProvider(model, use_fallbacks=kwargs.get("use_fallbacks", True))
    raise ValueError(f"Unknown provider {name!r}; expected 'openai', 'openai-compatible' or 'anthropic'")


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
