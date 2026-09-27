import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3").rstrip("/")
TOOLKIT_SLUG = "github"
PAGE_SIZE = 100
MAX_PAGES = 30


def _extract_page(payload: Any) -> tuple[list[Any], Any, int | None, int | None, int | None]:
    """Extract items and pagination metadata from a Composio tools response."""
    if isinstance(payload, list):
        return payload, None, None, None, None
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected Composio tools response format")

    body = payload.get("data", payload)
    if isinstance(body, list):
        return body, None, None, None, None
    if not isinstance(body, dict):
        raise RuntimeError("Unexpected Composio tools response format")

    items = body.get("items", body.get("tools"))
    if not isinstance(items, list):
        raise RuntimeError("Composio tools response did not contain an items list")

    next_cursor = body.get("next_cursor", payload.get("next_cursor"))
    total_pages = body.get("total_pages", payload.get("total_pages"))
    current_page = body.get("current_page", payload.get("current_page"))
    total_items = body.get("total_items", payload.get("total_items"))

    def as_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return items, next_cursor, as_int(total_pages), as_int(current_page), as_int(total_items)


@mcp.tool()
def get_github_action_count() -> str:
    """Return the exact number of actions available in Composio's GitHub toolkit.

    The tool lists GitHub actions from Composio's API and follows its pagination
    metadata so the count is based on the complete result, not an estimate.
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    endpoint = f"{API_BASE}/tools"
    headers = {"x-api-key": api_key}
    params: dict[str, Any] = {"toolkit_slug": TOOLKIT_SLUG, "limit": PAGE_SIZE}
    count = 0
    pages_fetched = 0
    seen_cursors: set[str] = set()
    expected_total: int | None = None

    with httpx.Client(timeout=10) as client:
        while pages_fetched < MAX_PAGES:
            response = client.get(endpoint, headers=headers, params=params)
            response.raise_for_status()
            items, next_cursor, total_pages, current_page, total_items = _extract_page(response.json())
            count += len(items)
            pages_fetched += 1
            if total_items is not None:
                expected_total = total_items

            if next_cursor:
                cursor = str(next_cursor)
                if cursor in seen_cursors:
                    raise RuntimeError("Composio returned a repeated pagination cursor")
                seen_cursors.add(cursor)
                params = {"toolkit_slug": TOOLKIT_SLUG, "limit": PAGE_SIZE, "cursor": cursor}
                continue

            if total_pages is not None and current_page is not None and current_page < total_pages:
                params = {
                    "toolkit_slug": TOOLKIT_SLUG,
                    "limit": PAGE_SIZE,
                    "page": current_page + 1,
                }
                continue

            if expected_total is not None and count != expected_total:
                raise RuntimeError("Composio pagination ended before all GitHub actions were retrieved")
            if total_pages is None and next_cursor is None and len(items) == PAGE_SIZE and expected_total is None:
                raise RuntimeError("Composio response may be paginated but provided no pagination metadata")
            break
        else:
            raise RuntimeError(f"Composio pagination exceeded the {MAX_PAGES}-page safety limit")

    return json.dumps(
        {
            "toolkit": TOOLKIT_SLUG,
            "action_count": count,
            "source_url": f"{endpoint}?toolkit_slug={TOOLKIT_SLUG}",
        }
    )


if __name__ == "__main__":
    mcp.run()
