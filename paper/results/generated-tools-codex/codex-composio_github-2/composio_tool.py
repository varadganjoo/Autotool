import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _headers() -> dict[str, str]:
    return {
        "x-api-key": os.environ["COMPOSIO_API_KEY"],
        "Accept": "application/json",
    }


def _extract_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "tools", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("items", "tools", "results"):
                value = nested.get(key)
                if isinstance(value, list):
                    return value
    return []


@mcp.tool()
def count_github_tools() -> str:
    """Count tools in the Composio GitHub toolkit.

    Returns:
        A JSON string with the count and the endpoint variant that succeeded.
    """
    attempts = [
        ("/api/v3/tools", {"toolkit_slug": "github", "limit": "1000"}),
        ("/api/v3/tools", {"toolkit": "github", "limit": "1000"}),
        ("/api/v3/tools", {"toolkit": "GITHUB", "limit": "1000"}),
        ("/api/v2/actions", {"appName": "github", "limit": "1000"}),
        ("/api/v2/actions", {"appName": "GITHUB", "limit": "1000"}),
    ]
    errors = []
    with httpx.Client(timeout=10, headers=_headers()) as client:
        for path, params in attempts:
            url = f"{API_BASE.rstrip('/')}{path}"
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                items = _extract_items(data)
                if items:
                    return json.dumps({
                        "count": len(items),
                        "endpoint": path,
                        "params": params,
                        "sample_names": [str(item.get("slug") or item.get("name") or item.get("key") or item.get("display_name")) for item in items[:10] if isinstance(item, dict)],
                    })
                errors.append({"path": path, "params": params, "status": response.status_code, "shape": type(data).__name__, "keys": list(data.keys())[:10] if isinstance(data, dict) else None})
            except Exception as exc:
                errors.append({"path": path, "params": params, "error": str(exc)[:200]})
    return json.dumps({"count": None, "errors": errors})

if __name__ == "__main__":
    mcp.run()
