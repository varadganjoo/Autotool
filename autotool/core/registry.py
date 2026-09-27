"""Live registry of mounted MCP servers. Owns every ``DynamicMCPClient`` and
routes namespaced tool calls (``<server>__<tool>``) to the right session."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result, sandbox_env
from autotool.core.schema import MCPToolDescriptor, ToolResult

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(
        self,
        tools_dir: str | Path = "tools",
        *,
        call_timeout_s: float = 30.0,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        self.tools_dir = Path(tools_dir).resolve()
        self.env_overrides = env_overrides or {}
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.call_timeout_s = call_timeout_s
        self._clients: dict[str, DynamicMCPClient] = {}
        self._routes: dict[str, tuple[str, str]] = {}  # qualified name -> (server, tool)

    # ---- mounting -------------------------------------------------------

    async def load_cached(self) -> list[str]:
        """Mount every verified script already in ``tools_dir``. Broken cache
        entries are logged and skipped rather than aborting startup."""
        mounted = []
        for path in sorted(self.tools_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                await self.mount(path)
                mounted.append(path.stem)
            except Exception as exc:  # noqa: BLE001 - keep booting with the rest
                log.warning("Skipping cached tool %s: %s", path.name, exc)
        return mounted

    async def mount(self, script_path: str | Path) -> list[MCPToolDescriptor]:
        """Hot-load (or reload) an MCP server script into the live session."""
        path = Path(script_path).resolve()
        name = path.stem
        if name in self._clients:
            await self.unmount(name)
        client = DynamicMCPClient(
            path, server_name=name, env=sandbox_env(self.env_overrides), call_timeout_s=self.call_timeout_s
        )
        tools = await client.connect()
        self._clients[name] = client
        for tool in tools:
            self._routes[tool.qualified_name] = (name, tool.name)
        log.info("Mounted %s with tools: %s", name, [t.name for t in tools])
        return tools

    async def unmount(self, server: str) -> None:
        client = self._clients.pop(server, None)
        self._routes = {q: r for q, r in self._routes.items() if r[0] != server}
        if client is not None:
            await client.close()

    async def close(self) -> None:
        for server in list(self._clients):
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
            return ToolResult(call_id=call_id, content=f"Tool call failed: {type(exc).__name__}: {exc}", is_error=True)
        return ToolResult(call_id=call_id, content=render_call_result(result) or "(empty result)", is_error=result.isError)

    async def __aenter__(self) -> "ToolRegistry":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
