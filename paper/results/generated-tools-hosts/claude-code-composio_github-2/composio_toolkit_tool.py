import json
import os
import httpx

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_tool")

COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")

# API key is optional for public tool listing; injected only if available.
REQUIRED_ENV = ["COMPOSIO_API_KEY"]


def _headers() -> dict:
    headers = {"Accept": "application/json"}
    key = os.environ.get("COMPOSIO_API_KEY")
    if key:
        headers["x-api-key"] = key
    return headers


@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count how many tools a given Composio toolkit exposes.

    Paginates through Composio's v3 tools listing filtered by toolkit and
    returns the total number of tools plus a sample of tool slugs.

    Parameters:
        toolkit_slug: The Composio toolkit slug to inspect (e.g. "github").
    """
    url = f"{COMPOSIO_API_BASE}/api/v3/tools"
    total = 0
    slugs: list[str] = []
    cursor = None
    with httpx.Client(timeout=10.0) as client:
        for _ in range(200):  # safety bound on pagination
            params = {"toolkit_slug": toolkit_slug, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(url, params=params, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data.get("data", []))
            total += len(items)
            for it in items:
                slug = it.get("slug") or it.get("name")
                if slug:
                    slugs.append(slug)
            cursor = data.get("next_cursor") or data.get("nextCursor")
            if not cursor or not items:
                break

    return json.dumps(
        {
            "toolkit_slug": toolkit_slug,
            "total_tools": total,
            "sample_tools": slugs[:20],
        }
    )


if __name__ == "__main__":
    mcp.run()
