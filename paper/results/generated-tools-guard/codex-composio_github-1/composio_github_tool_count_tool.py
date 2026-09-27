import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_tool_count_tool")
REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev")


def _headers():
    return {
        "x-api-key": os.environ["COMPOSIO_API_KEY"],
        "Accept": "application/json",
    }


def _extract_items(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "tools", "data", "actions", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_items(value)
            if nested:
                return nested
    return []


def _next_cursor(data):
    if not isinstance(data, dict):
        return None
    for key in ("next_cursor", "nextCursor", "cursor", "next"):
        value = data.get(key)
        if value:
            return value
    meta = data.get("meta") or data.get("pagination")
    if isinstance(meta, dict):
        for key in ("next_cursor", "nextCursor", "cursor", "next"):
            value = meta.get(key)
            if value:
                return value
    return None


@mcp.tool()
def count_github_tools() -> str:
    """Count tools/actions in Composio's GitHub toolkit using the Composio API.

    Returns a JSON string with the discovered count, endpoint, and a small sample of names.
    """
    endpoint_attempts = [
        ("/api/v3/tools", {"toolkit_slug": "github", "limit": "1000"}),
        ("/api/v3/tools", {"toolkits": "github", "limit": "1000"}),
        ("/api/v3/tools", {"toolkit": "github", "limit": "1000"}),
        ("/api/v3/tools", {"appName": "github", "limit": "1000"}),
        ("/api/v3/tools", {"toolkit_slug": "GITHUB", "limit": "1000"}),
        ("/api/v3/tools", {"toolkit": "GITHUB", "limit": "1000"}),
    ]
    errors = []
    with httpx.Client(timeout=10, headers=_headers()) as client:
        for path, params in endpoint_attempts:
            url = f"{API_BASE.rstrip('/')}{path}"
            try:
                response = client.get(url, params=params)
                if response.status_code >= 400:
                    errors.append({"endpoint": path, "params": params, "status": response.status_code, "body": response.text[:300]})
                    continue
                data = response.json()
                items = _extract_items(data)
                if not items:
                    errors.append({"endpoint": path, "params": params, "status": response.status_code, "body": response.text[:300]})
                    continue

                filtered = []
                for item in items:
                    text = json.dumps(item).lower() if isinstance(item, dict) else str(item).lower()
                    if "github" in text:
                        filtered.append(item)
                selected = filtered if filtered else items

                seen = list(selected)
                cursor = _next_cursor(data)
                guard = 0
                while cursor and guard < 20:
                    guard += 1
                    page_params = dict(params)
                    page_params["cursor"] = str(cursor)
                    page_response = client.get(url, params=page_params)
                    page_response.raise_for_status()
                    page_data = page_response.json()
                    page_items = _extract_items(page_data)
                    page_filtered = []
                    for item in page_items:
                        text = json.dumps(item).lower() if isinstance(item, dict) else str(item).lower()
                        if "github" in text:
                            page_filtered.append(item)
                    seen.extend(page_filtered if page_filtered else page_items)
                    next_cursor = _next_cursor(page_data)
                    if next_cursor == cursor:
                        break
                    cursor = next_cursor

                sample = []
                for item in seen[:10]:
                    if isinstance(item, dict):
                        sample.append(item.get("slug") or item.get("name") or item.get("display_name") or item.get("key") or str(item)[:80])
                    else:
                        sample.append(str(item)[:80])
                return json.dumps({"count": len(seen), "endpoint": path, "params": params, "sample": sample}, indent=2)
            except Exception as exc:
                errors.append({"endpoint": path, "params": params, "error": type(exc).__name__, "message": str(exc)[:300]})
    raise RuntimeError(json.dumps({"message": "Could not determine GitHub tool count", "errors": errors[:10]}, indent=2))


if __name__ == "__main__":
    mcp.run()
