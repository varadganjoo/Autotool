import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_count_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev").rstrip("/")
PAGE_SIZE = 100
MAX_PAGES = 100


def _page_parts(payload: Any) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Extract tool records and pagination details from a Composio response."""
    if isinstance(payload, list):
        return payload, None, False
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Composio tools response format")

    container = payload.get("data", payload)
    if isinstance(container, list):
        return container, None, False
    if not isinstance(container, dict):
        raise ValueError("Unexpected Composio tools response format")

    items = container.get("items")
    if items is None:
        items = container.get("tools")
    if items is None:
        items = container.get("results")
    if items is None and isinstance(container.get("data"), list):
        items = container["data"]
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Composio response did not contain a list of tool objects")

    pagination = container.get("pagination", payload.get("pagination", {}))
    if not isinstance(pagination, dict):
        pagination = {}
    cursor = (
        container.get("next_cursor")
        or container.get("nextCursor")
        or pagination.get("next_cursor")
        or pagination.get("nextCursor")
        or payload.get("next_cursor")
        or payload.get("nextCursor")
    )
    has_more = bool(
        container.get("has_more")
        or container.get("hasMore")
        or pagination.get("has_more")
        or pagination.get("hasMore")
        or payload.get("has_more")
        or payload.get("hasMore")
    )
    if cursor is not None and not isinstance(cursor, str):
        cursor = str(cursor)
    return items, cursor, has_more


def _tool_name(tool: dict[str, Any]) -> str | None:
    for key in ("name", "slug", "tool_slug", "tool_name", "id"):
        value = tool.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@mcp.tool()
def count_gmail_tools(include_tool_names: bool = True) -> str:
    """Retrieve Gmail's current Composio tool list and report its count.

    Args:
        include_tool_names: Include the retrieved tool names in the result to help verify the count.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    tools_by_identity: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    toolkit_name: str | None = None

    with httpx.Client(timeout=10.0, headers=headers) as client:
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"toolkit_slug": "gmail", "limit": PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{API_BASE}/api/v3/tools", params=params)
            response.raise_for_status()
            items, next_cursor, has_more = _page_parts(response.json())

            for tool in items:
                toolkit = tool.get("toolkit")
                if isinstance(toolkit, dict):
                    candidate = toolkit.get("name")
                    if isinstance(candidate, str) and candidate:
                        toolkit_name = candidate
                candidate = tool.get("toolkit_name")
                if isinstance(candidate, str) and candidate:
                    toolkit_name = candidate

                name = _tool_name(tool)
                identity_value = tool.get("id") or tool.get("slug") or tool.get("tool_slug") or name
                identity = str(identity_value) if identity_value is not None else json.dumps(tool, sort_keys=True)
                tools_by_identity.setdefault(identity, tool)

            if not next_cursor:
                if has_more:
                    raise RuntimeError("Composio indicated more tool results without providing a pagination cursor")
                break
            cursor = next_cursor
        else:
            raise RuntimeError("Composio tools pagination exceeded the configured page limit")

    names = sorted(name for tool in tools_by_identity.values() if (name := _tool_name(tool)))
    result: dict[str, Any] = {
        "toolkit": {"name": toolkit_name or "Gmail", "slug": "gmail"},
        "total_tools": len(tools_by_identity),
    }
    if include_tool_names:
        result["tool_names"] = names
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
