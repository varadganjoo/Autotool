"""Pydantic schemas shared across the runtime: tool descriptors, LLM turns,
synthesis requests/results and verification reports."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Module names become file names in ./tools and prefixes of public tool names.
TOOL_MODULE_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
# Anthropic / OpenAI function names: ^[a-zA-Z0-9_-]{1,64}$
FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
NAMESPACE_SEP = "__"


class MCPToolDescriptor(BaseModel):
    """A tool exposed by one mounted MCP server, as reported by ``list_tools``."""

    model_config = ConfigDict(frozen=True)

    server: str = Field(description="Tool module / server name, e.g. 'hackernews_tool'.")
    name: str = Field(description="Tool name inside the MCP server.")
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    @property
    def qualified_name(self) -> str:
        """Globally unique name exposed to the LLM: ``<server>__<tool>``."""
        return f"{self.server}{NAMESPACE_SEP}{self.name}"[:64]

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.qualified_name,
            "description": self.description or f"{self.name} (from {self.server})",
            "input_schema": _normalize_schema(self.input_schema),
        }

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description or f"{self.name} (from {self.server})",
                "parameters": _normalize_schema(self.input_schema),
            },
        }


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    schema = dict(schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMTurn(BaseModel):
    """Provider-neutral view of one assistant response."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: str | None = None
    # Provider-native assistant content, appended verbatim to history so that
    # thinking / fallback blocks survive round-trips.
    raw_content: Any = None


class ToolResult(BaseModel):
    call_id: str
    content: str
    is_error: bool = False


class CapabilityRequest(BaseModel):
    """What the orchestrator asks the synthesis engine to build."""

    tool_name: str = Field(description="snake_case module name, e.g. 'hackernews_tool'.")
    capability_description: str

    @field_validator("tool_name")
    @classmethod
    def _valid_module(cls, v: str) -> str:
        v = v.strip().lower().replace("-", "_")
        if not v.endswith("_tool"):
            v = f"{v}_tool"
        if not TOOL_MODULE_RE.match(v):
            raise ValueError(f"invalid tool module name: {v!r}")
        return v


class GeneratedToolCandidate(BaseModel):
    """Structured output the LLM returns when writing an MCP tool server (MCPServer)."""

    code: str = Field(description="Complete, self-contained Python source of the MCPServer tool script.")
    primary_tool: str = Field(description="Name of the most important @mcp.tool() function, used for the smoke test.")
    smoke_test_arguments_json: str = Field(
        description="JSON object of safe, realistic arguments for calling primary_tool in a smoke test, e.g. '{\"limit\": 3}'."
    )

    def smoke_test_arguments(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.smoke_test_arguments_json or "{}")
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None


class VerificationReport(BaseModel):
    ok: bool
    stage: Literal["static", "consent", "startup", "list_tools", "smoke_test", "passed"]
    tools: list[MCPToolDescriptor] = Field(default_factory=list)
    smoke_tool: str | None = None
    smoke_arguments: dict[str, Any] | None = None
    smoke_output: str | None = None
    error: str | None = None
    stderr: str = ""
    duration_s: float = 0.0

    def failure_summary(self, max_stderr: int = 4000) -> str:
        parts = [f"Verification failed at stage '{self.stage}'."]
        if self.error:
            parts.append(f"Error:\n{self.error}")
        if self.stderr.strip():
            parts.append(f"Server stderr (tail):\n{self.stderr[-max_stderr:]}")
        return "\n\n".join(parts)


class SynthesisResult(BaseModel):
    tool_name: str
    path: str
    attempts: int
    report: VerificationReport
