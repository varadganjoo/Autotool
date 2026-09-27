import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_counter_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


@mcp.tool()
def count_github_tools(toolkit: str = "github") -> str:
    """Count tools in a Composio toolkit.

    Args:
        toolkit: Toolkit slug/name to count, such as github.
    """
    slug = toolkit.lower()
    params = {"toolkit_slug": slug, "limit": 100}
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        resp = client.get(
            API_BASE.rstrip("/") + "/api/v3/tools",
            headers={"x-api-key": os.environ["COMPOSIO_API_KEY"], "Accept": "application/json"},
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
    items = data.get("items", []) if isinstance(data, dict) else []
    total = None
    for key in ("total_items", "total", "totalItems", "total_count", "count"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, int):
            total = value
            break
    sample_names = []
    for item in items[:15]:
        if isinstance(item, dict):
            sample_names.append(str(item.get("slug") or item.get("name") or item.get("key") or item.get("tool_name") or ""))
    return json.dumps({
        "endpoint": "/api/v3/tools",
        "params": params,
        "total_tools": total if total is not None else len(items),
        "page_items_returned": len(items),
        "total_pages": data.get("total_pages") if isinstance(data, dict) else None,
        "current_page": data.get("current_page") if isinstance(data, dict) else None,
        "next_cursor_present": bool(data.get("next_cursor")) if isinstance(data, dict) else False,
        "sample_names": sample_names,
    }, indent=2)


if __name__ == "__main__":
    mcp.run()
