"""AutoTool as a user-hosted MCP server: a tool layer that grows.

Any MCP host (Claude Code, Claude Desktop, Cursor, OpenClaw, or an agent you are building)
connects over stdio and gets:

- ``create_tool``: the agent writes an MCP tool script (MCPServer); AutoTool verifies it in a subprocess, gives
  it only the credentials it declares, mounts it and announces it with ``tools/list_changed``;
- ``synthesize_tool`` (only when a model key is configured): AutoTool writes the code itself;
- ``run_tool``: calls any mounted tool by name, for hosts that do not refresh their tool list;
- every mounted tool as a native tool, e.g. ``tavily_tool__search``.
"""

from __future__ import annotations

import contextvars
import json
import logging
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ToolsListChanged
from pydantic import ValidationError

from autotool import __version__
from autotool.core.credentials import autotool_home, load_tool_env
from autotool.core.llm import (
    DEFAULT_MODEL,
    DEFAULT_OPENAI_MODEL,
    AnthropicProvider,
    LLMProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
)
from autotool.core.policy import approve, code_hash
from autotool.core.registry import ToolRegistry
from autotool.core.schema import CapabilityRequest
from autotool.core.toolenv import required_env
from autotool.synthesis.generator import TEMPLATE, TOOL_CONTRACT, env_section
from autotool.synthesis.repair import SynthesisEngine, SynthesisError, promote
from autotool.synthesis.verifier import ToolVerifier

log = logging.getLogger(__name__)

CREATE_TOOL = "create_tool"
RUN_TOOL = "run_tool"
SYNTHESIZE_TOOL = "synthesize_tool"
MODERN_PROTOCOL = "2026-07-28"  # servers no longer send requests; consent rides on InputRequiredResult
_CONSENT_SCHEMA = {
    "type": "object",
    "properties": {"allow": {"type": "boolean", "title": "Allow", "default": False}},
    "required": ["allow"],
}
_ctx: contextvars.ContextVar[Any] = contextvars.ContextVar("autotool_request_context")
_NAME_SCHEMA = {"type": "string", "description": "snake_case module name ending in _tool, e.g. 'weather_tool'."}


def _result(text: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


class AutoToolServer:
    def __init__(
        self,
        home: Path | None = None,
        *,
        env_file: str | Path | None = None,
        provider: LLMProvider | None = None,
        consent: str = "prompt",
        sandbox: bool = True,
    ) -> None:
        """consent: "prompt" (ask the user before a tool first gets keys) or "auto".
        sandbox: run tools under autotool.guard; turn off when AutoTool itself runs in a sandbox."""
        self.home = home or autotool_home()
        self.env_file = env_file
        self.consent, self.sandbox = consent, sandbox
        self.tool_env = self._load_env()
        self.verifier = ToolVerifier(
            self.home / ".staging", tool_env=self.tool_env, consent=self.ask_consent if consent == "prompt" else None
        )
        self.registry = ToolRegistry(self.home / "tools", tool_env=self.tool_env)
        self.engine = SynthesisEngine(provider, tools_dir=self.home / "tools", verifier=self.verifier) if provider else None
        self.bus = InMemorySubscriptionBus()
        self.server = Server(
            "autotool",
            version=__version__,
            on_list_tools=self._on_list_tools,
            on_call_tool=self._on_call_tool,
            on_subscriptions_listen=ListenHandler(self.bus),
        )

    def refresh_env(self) -> None:
        """Re-read every credential source so keys added since startup work without a restart."""
        self.tool_env = self.verifier.tool_env = self.registry.tool_env = self._load_env()
        if self.engine:
            self.engine.generator.env_names = self.tool_env.names

    def _load_env(self):
        return load_tool_env(self.home, self.env_file, consent=self.consent == "prompt", guard=self.sandbox)

    def _consent_message(self, tool: str, keys: list[str], code: str) -> str:
        hosts = self.tool_env.allowed_hosts(keys) if self.sandbox else None
        reach = (
            f"It can only send them to {', '.join(hosts)}. Future versions won't ask again unless they need more."
            if hosts
            else "It can send them to any host, so every new version will ask again (limit a key with `autotool keys allow`)."
        )
        return f"AutoTool: allow the tool '{tool}' (code {code_hash(code)[:12]}) to use {', '.join(keys)}? {reach}"

    def _record_consent(self, result: types.ElicitResult, tool: str, keys: list[str], code: str) -> bool:
        if result.action == "accept" and (result.content or {}).get("allow") is True:
            approve(self.home, tool, keys, code, self.tool_env.allowed_hosts(keys) if self.sandbox else None)
            self.refresh_env()
            return True
        return False

    async def ask_consent(self, tool: str, keys: list[str], code: str) -> bool:
        """Legacy (pre-2026) connections: ask through a form elicitation. No secret is requested."""
        ctx = _ctx.get(None)
        if ctx is None or _modern(ctx) or not _can_prompt(ctx):
            return False  # modern connections were already asked, through InputRequiredResult
        result = await ctx.session.elicit_form(
            message=self._consent_message(tool, keys, code),
            requested_schema=_CONSENT_SCHEMA,
            related_request_id=ctx.request_id,
        )
        return self._record_consent(result, tool, keys, code)

    # ---- tool list ------------------------------------------------------

    def meta_tools(self) -> list[types.Tool]:
        create = types.Tool(
            name=CREATE_TOOL,
            description=(
                "Create a new tool when none of your current tools can do what the task needs (a web API, live "
                "data, a computation). Write a complete Python MCP tool server script (MCPServer); AutoTool verifies it in a "
                "guarded subprocess, injects only the credentials it declares, and mounts it: its tools appear "
                "in your tool list (or call them through run_tool). If verification fails you get the error; fix "
                "the code and call create_tool again with the same name.\n\nThe script MUST follow this contract:\n"
                f"{TOOL_CONTRACT}\n\n{env_section(self.tool_env.names)}\n\nStructural reference:\n```python\n{TEMPLATE}```"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": _NAME_SCHEMA,
                    "code": {"type": "string", "description": "Complete Python source of the MCPServer tool script."},
                    "test_tool": {"type": "string", "description": "Tool to smoke-test (default: the first one)."},
                    "test_arguments": {"type": "object", "description": "Safe, realistic arguments for the smoke test."},
                },
                "required": ["name", "code"],
            },
        )
        run = types.Tool(
            name=RUN_TOOL,
            description="Call a tool created with create_tool by its full name (e.g. 'weather_tool__current'). "
            "Use this if a newly created tool does not show up in your tool list.",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["name"],
            },
        )
        tools = [create, run]
        if self.engine:
            tools.append(
                types.Tool(
                    name=SYNTHESIZE_TOOL,
                    description="Have AutoTool write, verify and mount a new tool from a description (it uses its own "
                    "model). Prefer create_tool if you can write the code yourself.",
                    input_schema={
                        "type": "object",
                        "properties": {"tool_name": _NAME_SCHEMA, "capability_description": {"type": "string"}},
                        "required": ["tool_name", "capability_description"],
                    },
                )
            )
        return tools

    async def list_tools(self) -> list[types.Tool]:
        mounted = [
            types.Tool(name=d.qualified_name, description=d.description or d.name, input_schema=d.input_schema)
            for d in self.registry.descriptors()
        ]
        return [*self.meta_tools(), *mounted]

    # ---- dispatch -------------------------------------------------------

    async def _on_list_tools(self, ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=await self.list_tools())

    async def _on_call_tool(self, ctx: Any, params: types.CallToolRequestParams) -> Any:
        token = _ctx.set(ctx)
        try:
            return await self.call_tool(params.name, params.arguments or {}, params.input_responses)
        finally:
            _ctx.reset(token)

    async def call_tool(self, name: str, arguments: dict[str, Any], responses: dict[str, Any] | None = None) -> Any:
        if name == CREATE_TOOL:
            return await self.create_tool(arguments, responses)
        if name == SYNTHESIZE_TOOL and self.engine:
            return await self.synthesize_tool(arguments)
        if name == RUN_TOOL:
            name, arguments = str(arguments.get("name", "")), arguments.get("arguments") or {}
        result = await self.registry.call("call", name, arguments)
        return _result(result.content, result.is_error)

    async def create_tool(self, args: dict[str, Any], responses: dict[str, Any] | None = None) -> Any:
        try:
            tool_name = CapabilityRequest(tool_name=str(args.get("name", "")), capability_description="-").tool_name
        except ValidationError as exc:
            return _result(f"Invalid tool name: {exc.errors()[0]['msg']}", is_error=True)
        code = str(args.get("code", ""))
        self.refresh_env()
        ctx = _ctx.get(None)
        if self.consent == "prompt" and ctx is not None and _modern(ctx) and _can_prompt(ctx):
            try:
                keys = [n for n in required_env(code) if n in self.tool_env.names]
            except (ValueError, SyntaxError):
                keys = []  # the verifier reports the syntax error
            if keys and not self.tool_env.is_approved(tool_name, keys, code):
                answer = (responses or {}).get("consent")
                if answer is None:  # ask; the client retries this call with the answer in input_responses
                    form = types.ElicitRequestFormParams(
                        message=self._consent_message(tool_name, keys, code), requested_schema=_CONSENT_SCHEMA
                    )
                    return types.InputRequiredResult(input_requests={"consent": types.ElicitRequest(params=form)})
                if isinstance(answer, types.ElicitResult):
                    self._record_consent(answer, tool_name, keys, code)
        report = await self.verifier.verify(
            tool_name, code, primary_tool=args.get("test_tool"), smoke_arguments=args.get("test_arguments")
        )
        if not report.ok:
            try:
                missing = [n for n in required_env(code) if n not in self.tool_env.names]
            except (ValueError, SyntaxError):
                missing = []
            return _result(self._failure(report.failure_summary(), missing), is_error=True)
        path = promote(self.home / "tools", tool_name, code)
        (self.verifier.staging_dir / "pending" / f"{tool_name}.py").unlink(missing_ok=True)
        return await self._mount(path, f"verified (smoke test {report.smoke_tool} passed)")

    async def synthesize_tool(self, args: dict[str, Any]) -> types.CallToolResult:
        try:
            request = CapabilityRequest.model_validate(args)
        except ValidationError as exc:
            return _result(f"Invalid synthesize_tool arguments: {exc}", is_error=True)
        self.refresh_env()
        try:
            result = await self.engine.build_tool(request)
        except SynthesisError as exc:
            return _result(self._failure(str(exc), []), is_error=True)
        return await self._mount(Path(result.path), f"synthesized and verified in {result.attempts} attempt(s)")

    async def _mount(self, path: Path, origin: str) -> types.CallToolResult:
        try:
            tools = await self.registry.mount(path)
        except Exception as exc:
            return _result(self.tool_env.redact(f"Verified, but mounting failed: {type(exc).__name__}: {exc}"), is_error=True)
        await self.bus.publish(ToolsListChanged())  # 2026-era clients listen through subscriptions/listen
        ctx = _ctx.get(None)
        if ctx is not None and not _modern(ctx):
            await ctx.session.send_tool_list_changed()
        described = [{"name": t.qualified_name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        return _result(f"Tool server '{path.stem}' {origin} and mounted. New tools:\n{json.dumps(described, indent=2)}")

    @staticmethod
    def _failure(summary: str, missing: list[str]) -> str:
        text = summary + "\n\nFix the code and call create_tool again with the same name."
        if missing:
            adds = " and ".join(f"`autotool keys add {n}`" for n in missing)
            text += (
                f"\n\nIf the tool really needs {', '.join(missing)}, tell the user to add it with {adds} "
                "(or in ~/.autotool/.env), then retry."
            )
        return text

    # ---- run ------------------------------------------------------------

    async def run_stdio(self) -> None:
        async with self.registry:
            mounted = await self.registry.load_cached()
            log.info("AutoTool serving %d cached tool server(s); credentials available: %s", len(mounted), self.tool_env.names)
            if self.consent != "prompt":
                log.warning("Approvals are OFF (dangerously-allow-all): every tool gets the credentials it declares.")
            if not self.sandbox and self.tool_env.hosts:
                log.warning("Sandbox is off: host allowlists for %s are NOT enforced.", sorted(self.tool_env.hosts))
            async with stdio_server() as (read, write):
                options = self.server.create_initialization_options(NotificationOptions(tools_changed=True))
                await self.server.run(read, write, options)


def _modern(ctx: Any) -> bool:
    return (getattr(ctx, "protocol_version", None) or "") >= MODERN_PROTOCOL


def _can_prompt(ctx: Any) -> bool:
    return ctx.session.check_client_capability(types.ClientCapabilities(elicitation=types.ElicitationCapability()))


def model_provider(home: Path) -> LLMProvider | None:
    """Enable synthesize_tool only for a model key in ~/.autotool/.env. A key merely inherited from
    the host (e.g. the user's shell OPENAI_API_KEY seen by Claude Code) must not be billed silently."""
    found = dotenv_values(home / ".env") if (home / ".env").is_file() else {}
    try:
        # The key (and provider) come only from this file, never from the host's environment.
        if base_url := found.get("OPENAI_BASE_URL"):  # Ollama, LM Studio, vLLM, OpenRouter... (key optional)
            return OpenAICompatibleProvider(
                found.get("AUTOTOOL_OPENAI_MODEL") or found.get("OPENAI_LLM"),
                base_url=base_url,
                api_key=found.get("OPENAI_API_KEY") or "not-needed",
            )
        if key := found.get("OPENAI_API_KEY"):
            import openai

            model = found.get("AUTOTOOL_OPENAI_MODEL") or found.get("OPENAI_LLM") or DEFAULT_OPENAI_MODEL
            return OpenAIProvider(model, client=openai.AsyncOpenAI(api_key=key))
        if key := found.get("ANTHROPIC_API_KEY"):
            import anthropic

            return AnthropicProvider(found.get("AUTOTOOL_MODEL") or DEFAULT_MODEL, client=anthropic.AsyncAnthropic(api_key=key))
        return None
    except ValueError as exc:  # e.g. a base URL without a model name
        log.warning("synthesize_tool is off: %s", exc)
        return None
    except ImportError as exc:
        log.warning("synthesize_tool is off: %s. Install it with: pip install 'autotool-mcp[models]'", exc)
        return None


async def serve(env_file: str | Path | None = None, consent: str = "prompt", sandbox: bool = True) -> None:
    home = autotool_home()
    await AutoToolServer(home, env_file=env_file, provider=model_provider(home), consent=consent, sandbox=sandbox).run_stdio()
