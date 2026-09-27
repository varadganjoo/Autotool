"""Live registry of mounted MCP servers. Owns every ``DynamicMCPClient`` and
routes namespaced tool calls (``<server>__<tool>``) to the right session."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import anyio

from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result
from autotool.core.schema import MCPToolDescriptor, ToolResult
from autotool.core.toolenv import ToolEnv

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(
        self,
        tools_dir: str | Path = "tools",
        *,
        call_timeout_s: float = 30.0,
        env_overrides: dict[str, str] | None = None,
        tool_env: ToolEnv | None = None,
        mount_timeout_s: float = 20.0,
    ) -> None:
        self.tools_dir = Path(tools_dir).resolve()
        self.mount_timeout_s = mount_timeout_s  # a tool that hangs at start-up must not stall the server
        self.env_overrides = env_overrides or {}
        self.tool_env = tool_env or ToolEnv()
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.call_timeout_s = call_timeout_s
        self._clients: dict[str, DynamicMCPClient] = {}
        self._routes: dict[str, tuple[str, str]] = {}  # qualified name -> (server, tool)
        self._owners: dict[str, tuple[anyio.Event, anyio.Event]] = {}  # server -> (stop, done)
        self._locks: defaultdict[str, anyio.Lock] = defaultdict(anyio.Lock)  # one name mounts at a time

    # ---- mounting -------------------------------------------------------

    async def load_cached(self) -> list[str]:
        """Mount every verified script already in ``tools_dir``, concurrently (hosts time out
        slow MCP servers). Broken or hanging entries are logged and skipped."""
        mounted: list[str] = []

        async def one(path: Path) -> None:
            try:
                await self.mount(path)
                mounted.append(path.stem)
            except Exception as exc:  # noqa: BLE001 - keep booting with the rest
                log.warning("Skipping cached tool %s: %s", path.name, exc)

        async with anyio.create_task_group() as tg:
            for path in sorted(self.tools_dir.glob("*.py")):
                if not path.name.startswith("_"):
                    tg.start_soon(one, path)
        return sorted(mounted)

    async def mount(self, script_path: str | Path) -> list[MCPToolDescriptor]:
        """Hot-load (or reload) an MCP server script into the live session."""
        path = Path(script_path).resolve()
        async with self._locks[path.stem]:  # concurrent requests may mount (or replace) one name at once
            return await self._mount(path)

    async def _mount(self, path: Path) -> list[MCPToolDescriptor]:
        name = path.stem
        if name in self._owners:
            await self.unmount(name)
        # Least privilege: the process gets only the .env variables this script declares.
        env = self.tool_env.env_for(path.read_text(encoding="utf-8"), self.env_overrides, tool=name)
        client = DynamicMCPClient(
            path, server_name=name, env=env, call_timeout_s=self.call_timeout_s, connect_timeout_s=self.mount_timeout_s
        )
        # Schemas and descriptions go to the LLM every turn; a parameter default read from the
        # environment would put a secret there.
        raw = await self._tg.start(self._own, client)
        tools = [MCPToolDescriptor.model_validate(self.tool_env.redact_json(t.model_dump())) for t in raw]
        client.tools = tools
        self._clients[name] = client
        for tool in tools:
            self._routes[tool.qualified_name] = (name, tool.name)
        log.info("Mounted %s with tools: %s", name, [t.name for t in tools])
        return tools

    async def _own(self, client: DynamicMCPClient, *, task_status: Any = anyio.TASK_STATUS_IGNORED) -> None:
        """One owner task per server: an MCP stdio client must be opened and closed in the same
        task, and the task that mounts it (e.g. one MCP request) may end long before."""
        stop, done = anyio.Event(), anyio.Event()
        self._owners[client.server_name] = (stop, done)
        try:
            task_status.started(await client.connect())
            await stop.wait()
        finally:
            # No shield scope here: close() exits the client's own (older) cancel scopes.
            await client.close()
            done.set()

    async def unmount(self, server: str) -> None:
        self._clients.pop(server, None)
        self._routes = {q: r for q, r in self._routes.items() if r[0] != server}
        owner = self._owners.pop(server, None)
        if owner is not None:
            stop, done = owner
            stop.set()
            await done.wait()

    async def close(self) -> None:
        for server in list(self._owners):
            try:
                await self.unmount(server)
            except BaseException as exc:
                log.warning("Error closing %s: %s", server, exc)

    # ---- introspection --------------------------------------------------

    def has_server(self, server: str) -> bool:
        return server in self._clients

    @property
    def servers(self) -> list[str]:
        return list(self._clients)

    def descriptors(self) -> list[MCPToolDescriptor]:
        return [t for c in self._clients.values() for t in c.tools]

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.descriptors()]

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai() for t in self.descriptors()]

    def is_registered(self, qualified_name: str) -> bool:
        return qualified_name in self._routes

    # ---- dispatch -------------------------------------------------------

    async def call(self, call_id: str, qualified_name: str, arguments: dict[str, Any]) -> ToolResult:
        route = self._routes.get(qualified_name)
        if route is None:
            return ToolResult(call_id=call_id, content=f"Unknown tool '{qualified_name}'", is_error=True)
        server, tool = route
        client = self._clients[server]
        try:
            result = await client.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - surface to the LLM, keep running
            return ToolResult(
                call_id=call_id, content=self.tool_env.redact(f"Tool call failed: {type(exc).__name__}: {exc}"), is_error=True
            )
        content = self.tool_env.redact(render_call_result(result) or "(empty result)")
        return ToolResult(call_id=call_id, content=content, is_error=result.isError)

    async def __aenter__(self) -> "ToolRegistry":
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
        await self._tg.__aexit__(*exc)
