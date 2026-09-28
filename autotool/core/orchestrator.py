"""Main agent loop: plan with the LLM, dispatch MCP tool calls, and synthesize
missing capabilities on demand through the ``synthesize_tool`` meta-tool."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from autotool.core.llm import LLMProvider
from autotool.core.registry import ToolRegistry
from autotool.core.schema import CapabilityRequest, ToolCall, ToolResult
from autotool.synthesis.repair import SynthesisEngine, SynthesisError

log = logging.getLogger(__name__)

SYNTHESIZE_TOOL = "synthesize_tool"

SYNTHESIZE_TOOL_SCHEMA: dict[str, Any] = {
    "name": SYNTHESIZE_TOOL,
    "description": (
        "Create a brand-new tool when none of your current tools can do what the task needs "
        "(e.g. calling a specific public web API). AutoTool writes an MCP server for the capability, "
        "verifies it in a sandbox and mounts it; its tools appear in your tool list on the next turn. "
        "Describe the capability precisely: endpoints, inputs, and the exact output fields required."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "snake_case module name ending in _tool, e.g. 'hackernews_tool'.",
            },
            "capability_description": {
                "type": "string",
                "description": "What the tool must do, which public API to use, parameters and output format.",
            },
        },
        "required": ["tool_name", "capability_description"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are AutoTool, an autonomous agent that can extend its own toolset.

- Use your existing tools whenever they can accomplish the task.
- If the task needs an external capability none of your tools provide (live data, a web API, a
  computation you cannot do reliably), call `synthesize_tool` once per missing capability. After it
  succeeds, the new tools are in your tool list: call them to get the real data.
- Never invent data that should come from a tool. If synthesis fails, explain what failed.
- Give the final answer concisely, in the format the user asked for."""


def system_prompt(env_names: list[str]) -> str:
    """SYSTEM_PROMPT plus the names (never values) of credentials synthesized tools may use."""
    if not env_names:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + (
        "\n- Credentials and settings are available to tools you synthesize (values are injected at runtime "
        f"and never shown to you): {', '.join(env_names)}. When a task needs a service one of these unlocks, "
        "synthesize a tool for it and name the variable(s) in capability_description. If a task needs "
        "credentials that are not listed, say which are missing instead of guessing."
    )


class RunEvent(BaseModel):
    kind: str  # "llm" | "tool_call" | "tool_result" | "synthesis" | "final"
    detail: dict[str, Any] = Field(default_factory=dict)


class RunResult(BaseModel):
    answer: str
    steps: int
    synthesized: list[str] = Field(default_factory=list)
    elapsed_s: float = 0.0
    events: list[RunEvent] = Field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        engine: SynthesisEngine,
        *,
        max_steps: int = 12,
        max_syntheses: int = 3,
        on_event: Callable[[RunEvent], None] | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.engine = engine
        self.max_steps = max_steps
        self.max_syntheses = max_syntheses
        self.on_event = on_event
        self.messages: list[dict[str, Any]] = []

    def _emit(self, events: list[RunEvent], kind: str, **detail: Any) -> None:
        event = RunEvent(kind=kind, detail=detail)
        events.append(event)
        if self.on_event:
            self.on_event(event)

    def active_tools(self) -> list[dict[str, Any]]:
        return [*self.registry.anthropic_tools(), SYNTHESIZE_TOOL_SCHEMA]

    async def run(self, prompt: str) -> RunResult:
        self.messages.append({"role": "user", "content": prompt})
        events: list[RunEvent] = []
        synthesized: list[str] = []
        started = time.monotonic()
        system = system_prompt(self.registry.tool_env.names)

        for step in range(1, self.max_steps + 1):
            # Tool list is rebuilt every step so freshly mounted tools are visible immediately.
            tools = self.active_tools()
            turn = await self.provider.complete(system=system, messages=self.messages, tools=tools)
            self.messages.append(self.provider.assistant_message(turn))
            self._emit(events, "llm", step=step, text=turn.text, tool_calls=[c.name for c in turn.tool_calls])

            if not turn.tool_calls:
                self._emit(events, "final", text=turn.text)
                return RunResult(
                    answer=turn.text, steps=step, synthesized=synthesized, elapsed_s=time.monotonic() - started, events=events
                )

            results: list[ToolResult] = []
            for call in turn.tool_calls:
                self._emit(events, "tool_call", name=call.name, arguments=call.arguments)
                if call.name == SYNTHESIZE_TOOL:
                    result = await self._synthesize(call, synthesized, events)
                else:
                    result = await self.registry.call(call.id, call.name, call.arguments)
                self._emit(events, "tool_result", name=call.name, is_error=result.is_error, content=result.content[:2000])
                results.append(result)
            self.messages.extend(self.provider.tool_results_messages(results))

        raise RuntimeError(f"Agent did not finish within {self.max_steps} steps")

    async def _synthesize(self, call: ToolCall, synthesized: list[str], events: list[RunEvent]) -> ToolResult:
        try:
            request = CapabilityRequest.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(call_id=call.id, content=f"Invalid synthesize_tool arguments: {exc}", is_error=True)

        if self.registry.has_server(request.tool_name):
            return ToolResult(call_id=call.id, content=self._describe_server(request.tool_name, "already mounted"))

        if len(synthesized) >= self.max_syntheses:
            return ToolResult(call_id=call.id, content="Synthesis budget for this run is exhausted.", is_error=True)

        cached = self.engine.cached_path(request.tool_name)
        started = time.monotonic()
        try:
            if cached.exists():
                path, attempts, origin = cached, 0, "loaded from cache"
            else:
                result = await self.engine.build_tool(request)
                path, attempts, origin = result.path, result.attempts, f"synthesized and verified in {result.attempts} attempt(s)"
                synthesized.append(request.tool_name)
            await self.registry.mount(path)
        except SynthesisError as exc:
            self._emit(
                events,
                "synthesis",
                tool_name=request.tool_name,
                ok=False,
                attempts=exc.attempts,
                stage=exc.report.stage,
                error=exc.report.error,
                elapsed_s=time.monotonic() - started,
            )
            return ToolResult(call_id=call.id, content=str(exc), is_error=True)
        except Exception as exc:
            self._emit(events, "synthesis", tool_name=request.tool_name, ok=False, error=str(exc))
            return ToolResult(
                call_id=call.id, content=f"Failed to build or mount tool: {type(exc).__name__}: {exc}", is_error=True
            )

        self._emit(
            events,
            "synthesis",
            tool_name=request.tool_name,
            ok=True,
            attempts=attempts,
            path=str(path),
            elapsed_s=time.monotonic() - started,
        )
        return ToolResult(call_id=call.id, content=self._describe_server(request.tool_name, origin))

    def _describe_server(self, server: str, origin: str) -> str:
        tools = [
            {"name": t.qualified_name, "description": t.description, "input_schema": t.input_schema}
            for t in self.registry.descriptors()
            if t.server == server
        ]
        return f"Tool server '{server}' {origin} and mounted. New tools now available:\n{json.dumps(tools, indent=2)}"
