import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_gmail_tool_count_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3").rstrip("/")
TOOLS_ENDPOINT = f"{API_BASE}/tools"
PAGE_SIZE = 100
MAX_PAGES = 1000


def _page_items(payload: Any) -> list[dict[str, Any]]:
    """Extract tool records from common Composio catalog response envelopes."""
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Composio tools response: expected a JSON object")

    records: Any = payload.get("items", payload.get("tools", payload.get("data")))
    if isinstance(records, dict):
        records = records.get("items", records.get("tools"))
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ValueError("Unexpected Composio tools response: missing a list of tool records")
    return records


def _next_cursor(payload: dict[str, Any]) -> str | None:
    """Read a cursor from the response, including nested pagination envelopes."""
    pagination = payload.get("pagination")
    sources = [payload]
    if isinstance(pagination, dict):
        sources.append(pagination)

    for source in sources:
        for key in ("next_cursor", "nextCursor", "next"):
            value = source.get(key)
            if value is not None and value != "":
                if not isinstance(value, str):
                    raise ValueError("Unexpected Composio pagination cursor type")
                return value

    for source in sources:
        if source.get("has_more") is True or source.get("hasMore") is True:
            raise ValueError("Composio indicates more pages but supplied no pagination cursor")
    return None


def _record_toolkit_slug(record: dict[str, Any]) -> str | None:
    """Get a toolkit slug when the API includes it on a tool record."""
    for key in ("toolkit_slug", "toolkitSlug", "app_slug", "appSlug"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    for key in ("toolkit", "app"):
        value = record.get(key)
        if isinstance(value, dict):
            slug = value.get("slug") or value.get("toolkit_slug")
            if isinstance(slug, str):
                return slug
        elif isinstance(value, str):
            return value
    return None


@mcp.tool()
def count_gmail_tools() -> str:
    """Count all actions in Composio's Gmail toolkit by paging through its tool catalog.

    The Composio API key is read from the COMPOSIO_API_KEY environment variable.
    Returns the exact count, toolkit slug, and catalog endpoint used. The catalog
    is paginated until the API reports that no further cursor is available.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key, "accept": "application/json"}
    params: dict[str, Any] = {"toolkit_slug": "GMAIL", "limit": PAGE_SIZE}
    seen_cursors: set[str] = set()
    action_ids: set[str] = set()
    pages = 0

    with httpx.Client(timeout=10.0) as client:
        while True:
            if pages >= MAX_PAGES:
                raise RuntimeError("Composio catalog exceeded the pagination safety limit")
            response = client.get(TOOLS_ENDPOINT, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            records = _page_items(payload)
            pages += 1

            for record in records:
                toolkit_slug = _record_toolkit_slug(record)
                # The API query filters by toolkit; when records include a toolkit
                # identifier, verify it rather than counting unrelated entries.
                if toolkit_slug is not None and toolkit_slug.upper() != "GMAIL":
                    continue
                action_id = (
                    record.get("slug")
                    or record.get("tool_slug")
                    or record.get("toolSlug")
                    or record.get("id")
                )
                if action_id is None:
                    action_id = json.dumps(record, sort_keys=True, separators=(",", ":"))
                action_ids.add(str(action_id))

            cursor = _next_cursor(payload)
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ValueError("Composio returned a repeated pagination cursor")
            seen_cursors.add(cursor)
            params["cursor"] = cursor

    return json.dumps(
        {
            "toolkit_slug": "GMAIL",
            "tool_count": len(action_ids),
            "pages_fetched": pages,
            "source_endpoint": TOOLS_ENDPOINT,
            "query": {"toolkit_slug": "GMAIL", "limit": PAGE_SIZE},
        }
    )


if __name__ == "__main__":
    mcp.run()
