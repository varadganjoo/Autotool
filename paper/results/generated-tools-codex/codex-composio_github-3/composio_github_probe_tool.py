import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_github_probe_tool")
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


def _name(item):
    if not isinstance(item, dict):
        return str(item)[:160]
    fields = []
    for k in ("name", "slug", "display_name", "key", "toolkit", "toolkit_slug", "toolkitSlug", "appName", "app_name"):
        if k in item:
            fields.append(f"{k}={item.get(k)}")
    return "; ".join(fields)[:300]


@mcp.tool()
def probe_github_tools() -> str:
    """Probe selected Composio v3 endpoints and summarize counts/samples for GitHub filters."""
    endpoints = [
        "/api/v3/tools?toolkit=github",
        "/api/v3/tools?toolkit_slug=github",
        "/api/v3/tools?toolkits=github",
        "/api/v3/tools?appName=github",
        "/api/v3/toolkits?slug=github",
        "/api/v3/toolkits/github/tools",
    ]
    out = []
    headers = {"x-api-key": os.environ["COMPOSIO_API_KEY"], "Accept": "application/json"}
    with httpx.Client(timeout=3, headers=headers) as client:
        for path in endpoints:
            try:
                resp = client.get(COMPOSIO_API_BASE.rstrip("/") + path)
                rec = {"path": path, "status": resp.status_code, "content_type": resp.headers.get("content-type", "")[:60]}
                if resp.status_code == 200 and "json" in rec["content_type"].lower():
                    data = resp.json()
                    rec["top_keys"] = list(data.keys()) if isinstance(data, dict) else "list"
                    items = _extract_items(data)
                    if isinstance(items, list):
                        rec["count"] = len(items)
                        rec["sample"] = [_name(x) for x in items[:5]]
                        if isinstance(data, dict):
                            rec["meta"] = {k: data[k] for k in data.keys() if k.lower() in ("total", "count", "next", "page", "total_pages", "totalitems")}
                    else:
                        rec["snippet"] = json.dumps(data)[:700]
                else:
                    rec["snippet"] = resp.text[:250]
            except Exception as exc:
                rec = {"path": path, "error": type(exc).__name__, "message": str(exc)[:200]}
            out.append(rec)
    return json.dumps(out, indent=2)


if __name__ == "__main__":
    mcp.run()
