import os
import json
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("composio_toolkit_tool")

REQUIRED_ENV = ["COMPOSIO_API_KEY"]

COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _headers() -> dict:
    return {"Accept": "application/json", "x-api-key": os.environ["COMPOSIO_API_KEY"]}


@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count how many tools a Composio toolkit exposes.

    Queries Composio's tools API, paging through all results for the given
    toolkit and returning the total number of tools plus a sample of tool slugs.

    Parameters:
        toolkit_slug: The Composio toolkit slug to inspect (e.g. "github").
    """
    slug = toolkit_slug.strip().lower()
    url = f"{COMPOSIO_API_BASE}/api/v3/tools"
    tool_slugs: list[str] = []
    cursor = None
    total = None

    with httpx2.Client(timeout=10.0) as client:
        for _ in range(200):  # safety cap on paging
            params = {"toolkit_slug": slug, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(url, params=params, headers=_headers())
            if resp.status_code != 200:
                raise ToolError(
                    f"Composio tools API returned status {resp.status_code} for toolkit '{slug}'"
                )
            data = resp.json()
            items = data.get("items", data.get("data", [])) if isinstance(data, dict) else data
            for it in items:
                s = it.get("slug") or it.get("name")
                if s:
                    tool_slugs.append(s)
            if isinstance(data, dict) and data.get("total_items") is not None:
                total = data.get("total_items")
            cursor = data.get("next_cursor") if isinstance(data, dict) else None
            if not cursor or not items:
                break

    result = {
        "toolkit": slug,
        "tool_count": total if total is not None else len(tool_slugs),
        "tools_collected": len(tool_slugs),
        "sample_tools": tool_slugs[:20],
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
