import os
import json
from typing import Any

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("composio_github_toolkit_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _headers() -> dict[str, str]:
    return {"x-api-key": os.environ["COMPOSIO_API_KEY"]}


def _items(data: Any) -> list[Any]:
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    if isinstance(data, list):
        return data
    return []


@mcp.tool()
def github_tool_count() -> str:
    """Return the exact number of tools in Composio's GitHub toolkit."""
    with httpx2.Client(timeout=10) as client:
        first = client.get(
            f"{API_BASE}/api/v3/tools",
            headers=_headers(),
            params={"toolkit_slug": "github", "limit": 1},
        )
        if first.status_code != 200:
            raise ToolError(f"Composio API returned HTTP {first.status_code} for GitHub tools")
        data = first.json()
        for key in ("total", "total_count", "count"):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, int):
                return json.dumps({"count": value, "source": f"metadata.{key}", "response_keys": list(data.keys())})
        # Fall back to a high limit. The current catalog is small enough to fit in one bounded call.
        resp = client.get(
            f"{API_BASE}/api/v3/tools",
            headers=_headers(),
            params={"toolkit_slug": "github", "limit": 1000},
        )
        if resp.status_code != 200:
            raise ToolError(f"Composio API returned HTTP {resp.status_code} for GitHub tools fallback")
        full = resp.json()
        items = _items(full)
        if not items:
            raise ToolError("Composio API returned no tool list for GitHub toolkit")
        sample = []
        for item in items[:5]:
            if isinstance(item, dict):
                sample.append(str(item.get("slug") or item.get("name") or ""))
        return json.dumps({
            "count": len(items),
            "source": "items length from limit=1000",
            "response_keys": list(full.keys()) if isinstance(full, dict) else [],
            "sample": sample,
        })


@mcp.tool()
def github_tools_response_shape() -> str:
    """Return response metadata keys for the GitHub toolkit tools endpoint."""
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/api/v3/tools", headers=_headers(), params={"toolkit_slug": "github", "limit": 1})
        if resp.status_code != 200:
            raise ToolError(f"Composio API returned HTTP {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict):
            return json.dumps({"keys": list(data.keys()), "metadata": {k: v for k, v in data.items() if k != "items"}}, indent=2)
        return json.dumps({"type": type(data).__name__})


if __name__ == "__main__":
    mcp.run()
