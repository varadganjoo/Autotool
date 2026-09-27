import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")
mcp = FastMCP("composio_github_count_tool")


@mcp.tool()
def count_github_tools() -> str:
    """Count tools/actions in Composio's GitHub toolkit.

    Args:
        None.
    """
    headers = {"x-api-key": os.environ["COMPOSIO_API_KEY"], "accept": "application/json"}
    with httpx.Client(timeout=10, headers=headers) as client:
        response = client.get(f"{API_BASE}/api/v3/tools", params={"toolkit_slug": "github", "limit": 1})
        response.raise_for_status()
        data = response.json()
    return json.dumps(data)


if __name__ == "__main__":
    mcp.run()
