import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3").rstrip("/")
TOOLKIT_SLUG = "github"
PAGE_SIZE = 100
MAX_PAGES = 100

mcp = FastMCP("composio_github_tool")


def _extract_items(payload: Any) -> tuple[list[Any], dict[str, Any]]:
    """Return a page of tools and the object containing its pagination metadata."""
    if isinstance(payload, list):
        return payload, {}
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Composio tools response format")

    container = payload
    for key in ("items", "tools", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value, payload
        if isinstance(value, dict):
            container = value
            for nested_key in ("items", "tools"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested, value
    raise ValueError("Composio tools response did not contain a tools list")


def _reported_total(payload: Any, metadata: dict[str, Any]) -> int | None:
    """Read an explicit total count when the API supplies one."""
    candidates = [metadata]
    if isinstance(payload, dict) and payload is not metadata:
        candidates.append(payload)
    for obj in candidates:
        for key in ("total_count", "total_items", "total", "count"):
            value = obj.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
    return None


@mcp.tool()
def get_github_toolkit_tool_count() -> str:
    """Return Composio's exact number of tools in the GitHub toolkit.

    The tool queries the Composio tools-list API, following its pagination when
    necessary. It returns the toolkit slug, toolkit name, and exact tool count.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    params: dict[str, Any] = {"toolkit_slug": TOOLKIT_SLUG, "limit": PAGE_SIZE}
    all_tools: list[Any] = []
    seen_cursors: set[str] = set()
    toolkit_name = "GitHub"

    with httpx.Client(timeout=10.0, headers=headers) as client:
        for _ in range(MAX_PAGES):
            response = client.get(f"{API_BASE}/tools", params=params)
            response.raise_for_status()
            payload = response.json()
            items, metadata = _extract_items(payload)

            if isinstance(payload, dict):
                possible_name = payload.get("toolkit_name") or payload.get("name")
                toolkit = payload.get("toolkit")
                if isinstance(toolkit, dict):
                    possible_name = possible_name or toolkit.get("name")
                if isinstance(possible_name, str) and possible_name:
                    toolkit_name = possible_name
            if isinstance(metadata.get("toolkit"), dict):
                name = metadata["toolkit"].get("name")
                if isinstance(name, str) and name:
                    toolkit_name = name

            total = _reported_total(payload, metadata)
            if total is not None:
                result = {
                    "toolkit_slug": TOOLKIT_SLUG,
                    "toolkit_name": toolkit_name,
                    "tool_count": total,
                }
                return json.dumps(result)

            all_tools.extend(items)
            next_cursor = metadata.get("next_cursor") or metadata.get("nextCursor")
            if next_cursor is None and isinstance(metadata.get("pagination"), dict):
                pagination = metadata["pagination"]
                next_cursor = pagination.get("next_cursor") or pagination.get("nextCursor")

            if not next_cursor:
                return json.dumps({
                    "toolkit_slug": TOOLKIT_SLUG,
                    "toolkit_name": toolkit_name,
                    "tool_count": len(all_tools),
                })

            cursor = str(next_cursor)
            if cursor in seen_cursors:
                raise ValueError("Composio returned a repeated pagination cursor")
            seen_cursors.add(cursor)
            params["cursor"] = cursor

    raise ValueError("Composio tools pagination exceeded the safety limit")


if __name__ == "__main__":
    mcp.run()
