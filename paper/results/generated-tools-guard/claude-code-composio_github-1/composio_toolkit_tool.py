import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _headers() -> dict:
    key = os.environ.get("COMPOSIO_API_KEY", "")
    headers = {"Accept": "application/json"}
    if key:
        headers["x-api-key"] = key
    return headers


@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count how many tools a Composio toolkit exposes.

    Queries the Composio v3 tools API filtered by toolkit and paginates through
    all results to get an accurate total count.

    Parameters:
        toolkit_slug: The toolkit slug on Composio, e.g. 'github', 'slack', 'gmail'.
    """
    url = f"{COMPOSIO_API_BASE}/api/v3/tools"
    total = 0
    sample = []
    cursor = None
    with httpx.Client(timeout=10.0) as client:
        for _ in range(200):  # safety bound on pages
            params = {"toolkit_slug": toolkit_slug, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(url, headers=_headers(), params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data.get("data", []))
            total += len(items)
            if len(sample) < 10:
                for it in items:
                    slug = it.get("slug") or it.get("name")
                    if slug:
                        sample.append(slug)
            cursor = data.get("next_cursor") or data.get("nextCursor")
            if not cursor or not items:
                break
    return json.dumps({
        "toolkit": toolkit_slug,
        "tool_count": total,
        "sample_tools": sample[:10],
    })


if __name__ == "__main__":
    mcp.run()
