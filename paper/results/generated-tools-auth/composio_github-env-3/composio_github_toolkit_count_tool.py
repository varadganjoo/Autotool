import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_toolkit_count_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get(
    "COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3"
).rstrip("/")
TOOLKIT_SLUG = "github"
PAGE_LIMIT = 100


def _find_toolkit_name(value: Any) -> str | None:
    """Find a toolkit's display name in common Composio response shapes."""
    if isinstance(value, dict):
        for key in ("name", "display_name", "displayName", "toolkit_name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for key in ("toolkit", "data", "item", "result"):
            if key in value:
                candidate = _find_toolkit_name(value[key])
                if candidate:
                    return candidate
    return None


def _page_items(payload: Any) -> tuple[list[Any], Any, bool | None]:
    """Extract action records and pagination information from an API response."""
    if isinstance(payload, list):
        return payload, None, None
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Composio tools response format")

    body = payload
    for key in ("items", "tools", "results"):
        records = body.get(key)
        if isinstance(records, list):
            return records, _next_cursor(body), _has_more(body)

    data = body.get("data")
    if isinstance(data, list):
        return data, _next_cursor(body), _has_more(body)
    if isinstance(data, dict):
        for key in ("items", "tools", "results"):
            records = data.get(key)
            if isinstance(records, list):
                return records, _next_cursor(data) or _next_cursor(body), _has_more(data)
        # Some API response envelopes put pagination alongside a nested result.
        for key in ("items", "tools", "results"):
            records = data.get(key)
            if isinstance(records, list):
                return records, _next_cursor(body), _has_more(body)

    raise ValueError("Composio tools response did not contain an action list")


def _next_cursor(payload: dict[str, Any]) -> Any:
    for key in ("next_cursor", "nextCursor"):
        value = payload.get(key)
        if value:
            return value
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        for key in ("next_cursor", "nextCursor", "next"):
            value = pagination.get(key)
            if value:
                return value
    return None


def _has_more(payload: dict[str, Any]) -> bool | None:
    for key in ("has_more", "hasMore"):
        value = payload.get(key)
        if isinstance(value, bool):
            return value
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        for key in ("has_more", "hasMore"):
            value = pagination.get(key)
            if isinstance(value, bool):
                return value
    return None


def _action_identity(action: Any) -> str | None:
    if not isinstance(action, dict):
        return None
    for key in ("slug", "tool_slug", "id", "name"):
        value = action.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return None


@mcp.tool()
def count_github_toolkit_tools() -> str:
    """Fetch and count all available actions in Composio's GitHub toolkit.

    The count is based on action records returned by Composio's paginated tools
    endpoint. The toolkit metadata endpoint supplies the exact display name.
    This tool takes no parameters.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key, "accept": "application/json"}
    toolkit_endpoint = f"{API_BASE}/toolkits/{TOOLKIT_SLUG}"
    tools_endpoint = f"{API_BASE}/tools"

    with httpx.Client(timeout=10.0, headers=headers) as client:
        toolkit_response = client.get(toolkit_endpoint)
        toolkit_response.raise_for_status()
        toolkit_payload = toolkit_response.json()
        toolkit_name = _find_toolkit_name(toolkit_payload)

        actions: list[Any] = []
        seen: set[str] = set()
        cursor: Any = None
        visited_cursors: set[str] = set()
        page_count = 0
        while True:
            params: dict[str, Any] = {
                "toolkit_slug": TOOLKIT_SLUG,
                "limit": PAGE_LIMIT,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = client.get(tools_endpoint, params=params)
            response.raise_for_status()
            page_count += 1
            records, next_cursor, has_more = _page_items(response.json())

            for action in records:
                identity = _action_identity(action)
                if identity is None:
                    # Keep unidentifiable records distinct rather than silently
                    # dropping a valid action from the total.
                    actions.append(action)
                elif identity not in seen:
                    seen.add(identity)
                    actions.append(action)

            if not next_cursor:
                if has_more:
                    raise ValueError(
                        "Composio indicates more tool pages exist but supplied no next cursor"
                    )
                break
            cursor_key = str(next_cursor)
            if cursor_key in visited_cursors:
                raise ValueError("Composio returned a repeated pagination cursor")
            visited_cursors.add(cursor_key)
            cursor = next_cursor

    if not toolkit_name:
        # The toolkit details response must provide the exact name; avoid
        # substituting an inferred or estimated display name.
        raise ValueError("Composio toolkit metadata did not include its exact name")

    result = {
        "toolkit": {"name": toolkit_name, "slug": TOOLKIT_SLUG},
        "tool_count": len(actions),
        "evidence": {
            "toolkit_endpoint": toolkit_endpoint,
            "actions_endpoint": tools_endpoint,
            "actions_filter": {"toolkit_slug": TOOLKIT_SLUG},
            "pages_fetched": page_count,
            "page_limit": PAGE_LIMIT,
        },
    }
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
