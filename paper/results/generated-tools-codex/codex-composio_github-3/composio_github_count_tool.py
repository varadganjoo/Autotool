import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_count_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _extract_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "actions", "tools", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                nested = _extract_items(val)
                if nested is not None:
                    return nested
    return None


@mcp.tool()
def count_github_tools() -> str:
    """Count tools/actions in Composio's GitHub toolkit using the Composio API."""
    endpoints = [
        "/api/v3/tools?toolkit=github",
        "/api/v3/tools?toolkit=GITHUB",
        "/api/v3/tools?toolkit_slug=github",
        "/api/v3/tools?toolkit_slug=GITHUB",
        "/api/v3/tools?toolkitId=github",
        "/api/v3/toolkits/github/tools",
        "/api/v3/toolkits/GITHUB/tools",
        "/api/v3/toolkits/github/actions",
    ]
    attempts = []
    headers = {"x-api-key": os.environ["COMPOSIO_API_KEY"], "Accept": "application/json"}
    with httpx.Client(timeout=10, headers=headers) as client:
        for path in endpoints:
            url = COMPOSIO_API_BASE.rstrip("/") + path
            resp = client.get(url)
            content_type = resp.headers.get("content-type", "")
            record = {"path": path, "status": resp.status_code}
            if resp.status_code == 200 and "json" in content_type.lower():
                data = resp.json()
                items = _extract_items(data)
                if isinstance(items, list):
                    record["count"] = len(items)
                    record["sample"] = [str((x.get("name") or x.get("slug") or x.get("display_name") or x.get("key") or x) if isinstance(x, dict) else x)[:120] for x in items[:5]]
                    return json.dumps(record, indent=2)
                record["keys"] = list(data.keys()) if isinstance(data, dict) else type(data).__name__
                record["snippet"] = json.dumps(data)[:500]
            else:
                record["snippet"] = resp.text[:500]
            attempts.append(record)
    return json.dumps({"error": "no usable endpoint", "attempts": attempts}, indent=2)


if __name__ == "__main__":
    mcp.run()
