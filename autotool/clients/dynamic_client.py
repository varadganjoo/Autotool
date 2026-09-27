"""Async stdio MCP client that spawns a tool script as a child process and keeps
a live ``ClientSession`` to it, so tools can be called mid-reasoning without
restarting the parent runtime."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from contextlib import AsyncExitStack
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from autotool.core.schema import MCPToolDescriptor

# Environment variables that must never leak into synthesized code.
_SECRET_ENV_RE = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
# What a tool may inherit: OS basics, locale, proxy and CA settings, and `<SERVICE>_API_BASE`
# overrides. Hosts such as Claude Code hand MCP servers their whole environment (AWS keys,
# DATABASE_URL, ...), so this is an allowlist, not a denylist.
_INHERIT = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LANGUAGE", "TZ", "HTTP_PROXY", "HTTPS_PROXY",
    "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
}


def _inheritable(name: str) -> bool:
    upper = name.upper()
    return (upper in _INHERIT or upper.startswith("LC_") or upper.endswith("_API_BASE")) and not _SECRET_ENV_RE.search(name)


def sandbox_env(extra: dict[str, str] | None = None, drop: Iterable[str] = ()) -> dict[str, str]:
    """Allowlisted parent environment minus ``drop`` (every credential-source name, so a tool
    only sees the ones granted to it through ``extra``). Keeps PATH, proxy and CA settings so
    generated tools can still reach the network the host is allowed to reach."""
    dropped = {name.upper() for name in drop}
    env = {k: v for k, v in os.environ.items() if _inheritable(k) and k.upper() not in dropped}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def render_call_result(result: CallToolResult) -> str:
    """Flatten MCP content blocks into text for the LLM."""
    chunks: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            chunks.append(block.text)
        else:
            chunks.append(f"[{block.type} content omitted]")
    if not chunks and result.structuredContent is not None:
        chunks.append(str(result.structuredContent))
    return "\n".join(chunks)


class DynamicMCPClient:
    """One live connection to one MCP server script."""

    def __init__(
        self,
        script_path: str | Path,
        *,
        server_name: str | None = None,
        env: dict[str, str] | None = None,
        call_timeout_s: float = 30.0,
        errlog: TextIO | None = None,
        connect_timeout_s: float | None = None,
    ) -> None:
        self.script_path = Path(script_path).resolve()
        self.server_name = server_name or self.script_path.stem
        self.env = env
        self.call_timeout = timedelta(seconds=call_timeout_s)
        # Bounds initialize/list_tools; tool calls pass their own timeout.
        self.connect_timeout = timedelta(seconds=connect_timeout_s) if connect_timeout_s else None
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        # Caller-owned errlog outlives the connection (the verifier reads it after
        # a failed startup); otherwise a temp file is managed per connection.
        self._external_errlog = errlog
        self._errlog: TextIO | None = errlog
        self.tools: list[MCPToolDescriptor] = []

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> list[MCPToolDescriptor]:
        """Spawn the script with ``sys.executable``, initialize, and list tools.

        Must be closed from the same asyncio task that opened it (anyio cancel
        scopes are task-bound)."""
        if self._session is not None:
            return self.tools
        env = self.env if self.env is not None else sandbox_env()
        args = [str(self.script_path)]
        if "AUTOTOOL_GUARD" in env:  # run under the in-process guard (autotool/guard.py)
            args = ["-m", "autotool.guard", *args]
            env = {**env, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}  # so -m finds autotool
        params = StdioServerParameters(command=sys.executable, args=args, env=env, cwd=str(self.script_path.parent))
        stack = AsyncExitStack()
        try:
            # stderr goes to a real file so it can be surfaced on failure.
            if self._external_errlog is None:
                self._errlog = stack.enter_context(
                    tempfile.TemporaryFile(mode="w+", encoding="utf-8", prefix=f"{self.server_name}-", suffix=".log")
                )
            read, write = await stack.enter_async_context(stdio_client(params, errlog=self._errlog))
            session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=self.connect_timeout))
            await session.initialize()
            self._stack, self._session = stack, session
            await self.refresh_tools()
        except BaseException:
            self._session = None
            await stack.aclose()
            raise
        return self.tools

    async def refresh_tools(self) -> list[MCPToolDescriptor]:
        listed = await self._require_session().list_tools()
        self.tools = [
            MCPToolDescriptor(
                server=self.server_name,
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {"type": "object", "properties": {}},
            )
            for t in listed.tools
        ]
        return self.tools

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.tools]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai() for t in self.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> CallToolResult:
        return await self._require_session().call_tool(
            tool_name, arguments or {}, read_timeout_seconds=self.call_timeout
        )

    def read_stderr(self) -> str:
        if self._errlog is None or self._errlog.closed:
            return ""
        self._errlog.flush()
        pos = self._errlog.tell()
        self._errlog.seek(0)
        text = self._errlog.read()
        self._errlog.seek(pos)
        return text

    async def close(self) -> None:
        """Close the session; the stdio transport terminates the child process."""
        stack, self._stack, self._session = self._stack, None, None
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException:
                pass

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError(f"MCP server '{self.server_name}' is not connected")
        return self._session

    async def __aenter__(self) -> "DynamicMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
