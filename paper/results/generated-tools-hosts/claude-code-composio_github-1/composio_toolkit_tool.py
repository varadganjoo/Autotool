import json
import os
import httpx

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count how many tools (actions) a given Composio toolkit exposes.

    Iterates through all paginated tool listings for the toolkit and returns
    the total count plus the tool slugs.

    Parameters:
        toolkit_slug: The Composio toolkit slug, e.g. "github", "slack".
    """
    api_key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": api_key}
    url = f"{COMPOSIO_API_BASE}/api/v3/tools"

    tools = []
    cursor = None
    with httpx.Client(timeout=10.0, headers=headers) as client:
        while True:
            params = {"toolkit_slug": toolkit_slug.lower(), "limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data.get("data", []))
            for it in items:
                slug = it.get("slug") or it.get("name")
                if slug:
                    tools.append(slug)
            cursor = data.get("next_cursor") or data.get("nextCursor")
            if not cursor or not items:
                break

    return json.dumps({
        "toolkit": toolkit_slug,
        "tool_count": len(tools),
        "tools": tools,
    })


if __name__ == "__main__":
    mcp.run()
