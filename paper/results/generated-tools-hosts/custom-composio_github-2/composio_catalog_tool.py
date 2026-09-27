import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
API_KEY = os.environ["COMPOSIO_API_KEY"]
mcp = FastMCP("composio_catalog_tool")

@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count tools available for a Composio toolkit.

    Args:
        toolkit_slug: Composio toolkit slug to inspect, such as github.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/tools", params={"toolkit_slug": toolkit_slug, "limit": 1000}, headers={"x-api-key": API_KEY})
        response.raise_for_status()
        return response.text

if __name__ == "__main__":
    mcp.run()
