import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
COMPOSIO_API_KEY = os.environ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")
mcp = FastMCP("composio_count_tool")

@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count tools in a Composio toolkit using Composio's catalog API.

    Args:
        toolkit_slug: Toolkit slug to count, for example github.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/api/v3.1/tools",
            headers={"x-api-key": COMPOSIO_API_KEY},
            params={"toolkit_slug": toolkit_slug, "limit": 1000, "include_deprecated": "false"},
        )
        response.raise_for_status()
        data = response.json()
    items = data.get("items", [])
    count = data.get("total_items")
    if count is None:
        count = len(items)
    return f"{toolkit_slug}: {count} tools in the Composio catalog (current API response)."

if __name__ == "__main__":
    mcp.run()
