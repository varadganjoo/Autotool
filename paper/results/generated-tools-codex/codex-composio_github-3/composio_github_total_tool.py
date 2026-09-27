import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_total_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


@mcp.tool()
def github_total() -> str:
    """Return the total number of tools in Composio's GitHub toolkit."""
    headers = {"x-api-key": os.environ["COMPOSIO_API_KEY"], "Accept": "application/json"}
    params = {"toolkit_slug": "github"}
    with httpx.Client(timeout=10, headers=headers) as client:
        resp = client.get(COMPOSIO_API_BASE.rstrip("/") + "/api/v3/tools", params=params)
        resp.raise_for_status()
        data = resp.json()
        result = {
            "total_items": data.get("total_items"),
            "total_pages": data.get("total_pages"),
            "current_page": data.get("current_page"),
            "page_count": len(data.get("items", [])),
            "first_tool": (data.get("items") or [{}])[0].get("slug"),
        }
        return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
