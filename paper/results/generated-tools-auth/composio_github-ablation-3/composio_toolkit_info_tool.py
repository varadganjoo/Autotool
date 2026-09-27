import html
import json
import os
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_info_tool")

# These are public Composio pages; neither requires credentials.
COMPOSIO_WEB_BASE = os.environ.get("COMPOSIO_WEB_BASE", "https://composio.dev").rstrip("/")
COMPOSIO_DOCS_BASE = os.environ.get("COMPOSIO_DOCS_BASE", "https://docs.composio.dev").rstrip("/")
SOURCE_URLS = [
    f"{COMPOSIO_WEB_BASE}/toolkits/github",
    f"{COMPOSIO_DOCS_BASE}/toolkits/github",
    f"{COMPOSIO_DOCS_BASE}/tools/github",
]
COUNT_KEYS = {
    "actions_count", "action_count", "tools_count", "tool_count",
    "total_actions", "total_tools", "actionsCount", "actionCount",
    "toolsCount", "toolCount", "totalActions", "totalTools",
}


def _count_in_data(value: Any) -> int | None:
    """Find an explicitly named total-count field in embedded page data."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in COUNT_KEYS and isinstance(item, int) and not isinstance(item, bool):
                return item
        for item in value.values():
            found = _count_in_data(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _count_in_data(item)
            if found is not None:
                return found
    return None


def _extract_count(page: str) -> int | None:
    """Extract only an explicit total from structured data or page text."""
    for match in re.finditer(r"(?:__NEXT_DATA__|application/json)[^>]*>(.*?)</script", page, re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        try:
            count = _count_in_data(json.loads(raw))
            if count is not None:
                return count
        except (json.JSONDecodeError, TypeError):
            pass

    # Toolkit pages commonly render the total as a short label such as "42 actions".
    text = html.unescape(re.sub(r"<[^>]*>", " ", page))
    text = re.sub(r"\s+", " ", text)
    patterns = (
        r"\b(\d+)\s+(?:available\s+)?(?:tools|actions)\b",
        r"\b(?:tools|actions)\s*[:(]\s*(\d+)\b",
        r"\btotal\s+(?:tools|actions)\s*[:=]?\s*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


@mcp.tool()
def get_github_toolkit_info() -> str:
    """Retrieve Composio's current public GitHub toolkit information.

    Fetches Composio's public toolkit or documentation page and returns its toolkit
    name, explicitly published total tool/action count, and the page URL used.
    Raises an error rather than guessing if no exact count is published.
    """
    with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "ComposioToolkitInfo/1.0"}) as client:
        for url in SOURCE_URLS:
            response = client.get(url)
            if response.status_code in (404, 410):
                continue
            response.raise_for_status()
            count = _extract_count(response.text)
            if count is not None:
                return json.dumps({
                    "toolkit_name": "GitHub",
                    "total_tools_actions": count,
                    "source_url": str(response.url),
                })

    raise ValueError("Composio's public GitHub pages did not publish an exact tool/action total")


if __name__ == "__main__":
    mcp.run()
