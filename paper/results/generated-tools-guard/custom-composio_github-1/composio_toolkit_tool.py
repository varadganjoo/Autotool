import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
API_KEY = os.environ["COMPOSIO_API_KEY"]
mcp = FastMCP("composio_toolkit_tool")


@mcp.tool()
def github_tool_count() -> str:
    """Get the number of tools in Composio's GitHub toolkit.

    This fetches GitHub toolkit tools from the Composio API and follows pagination
    where available, returning the total count reported or counted.
    """
    headers = {"x-api-key": API_KEY, "accept": "application/json"}
    collected = 0
    cursor = None
    reported_total = None
    with httpx.Client(timeout=10) as client:
        for _ in range(30):
            params = {"toolkit_slug": "github", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{API_BASE}/tools", headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                rows = data
                next_cursor = None
            elif isinstance(data, dict):
                rows = data.get("items", data.get("tools", data.get("data", [])))
                if isinstance(rows, dict):
                    rows = rows.get("items", rows.get("tools", []))
                meta = data.get("meta", {})
                reported_total = data.get("total", data.get("count", meta.get("total") if isinstance(meta, dict) else None)) or reported_total
                pagination = data.get("pagination", {})
                next_cursor = data.get("next_cursor") or data.get("nextCursor") or (pagination.get("next_cursor") if isinstance(pagination, dict) else None)
            else:
                raise ValueError("Unexpected response format from Composio API")
            if not isinstance(rows, list):
                raise ValueError("Could not find a tool list in Composio API response")
            collected += len(rows)
            if not next_cursor or not rows:
                break
            cursor = next_cursor
    return json.dumps({"toolkit": "github", "tool_count": reported_total if reported_total is not None else collected})


if __name__ == "__main__":
    mcp.run()
