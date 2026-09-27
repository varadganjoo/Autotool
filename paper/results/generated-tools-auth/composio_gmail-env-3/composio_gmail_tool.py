import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_gmail_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3").rstrip("/")


def _find_items(payload: Any) -> list[Any]:
    """Extract a tool list from common Composio response envelopes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "tools", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for key in ("data", "result"):
            if key in payload:
                try:
                    return _find_items(payload[key])
                except ValueError:
                    pass
    raise ValueError("Composio tool-list response did not contain a tool list")


def _find_next_cursor(payload: Any) -> Any:
    """Read a pagination cursor from a response, including nested envelopes."""
    if isinstance(payload, dict):
        for key in ("next_cursor", "nextCursor"):
            if key in payload:
                return payload[key]
        for key in ("data", "result", "pagination"):
            if key in payload:
                cursor = _find_next_cursor(payload[key])
                if cursor is not None:
                    return cursor
    return None


def _find_toolkit_identifier(payload: Any) -> str:
    """Prefer a toolkit slug from metadata, falling back to the requested slug."""
    if isinstance(payload, dict):
        for key in ("slug", "toolkit_slug", "toolkitSlug"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("toolkit", "data", "result"):
            if key in payload:
                identifier = _find_toolkit_identifier(payload[key])
                if identifier != "gmail":
                    return identifier
    elif isinstance(payload, list):
        for item in payload:
            identifier = _find_toolkit_identifier(item)
            if identifier != "gmail":
                return identifier
    return "gmail"


def _tool_name(item: Any) -> str | None:
    if isinstance(item, dict):
        for key in ("slug", "name", "tool_name", "toolName"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


@mcp.tool()
def get_gmail_toolkit_metadata() -> str:
    """Retrieve Gmail toolkit metadata and the exact count and names of its tools.

    The Composio API key is read from COMPOSIO_API_KEY. The tool requests the
    Gmail toolkit metadata and paginates through Composio's Gmail tool listing.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key, "Accept": "application/json"}

    with httpx.Client(timeout=10.0, headers=headers) as client:
        metadata_response = client.get(f"{API_BASE}/toolkits/gmail")
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        toolkit_identifier = _find_toolkit_identifier(metadata)

        all_tools: list[Any] = []
        cursor: Any = None
        seen_cursors: set[str] = set()
        for _ in range(100):
            params: dict[str, Any] = {"toolkit_slug": "gmail", "limit": 100}
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(f"{API_BASE}/tools", params=params)
            response.raise_for_status()
            page = response.json()
            all_tools.extend(_find_items(page))
            next_cursor = _find_next_cursor(page)
            if next_cursor in (None, ""):
                break
            cursor_key = str(next_cursor)
            if cursor_key in seen_cursors:
                raise RuntimeError("Composio tool listing returned a repeated pagination cursor")
            seen_cursors.add(cursor_key)
            cursor = next_cursor
        else:
            raise RuntimeError("Composio tool listing exceeded the pagination safety limit")

    result = {
        "toolkit_identifier": toolkit_identifier,
        "tool_count": len(all_tools),
        "tool_names": [name for item in all_tools if (name := _tool_name(item)) is not None],
    }
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
