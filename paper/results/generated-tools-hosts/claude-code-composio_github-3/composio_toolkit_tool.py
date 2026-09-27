import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_toolkit_tool")

COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev")


@mcp.tool()
def count_toolkit_tools(toolkit_slug: str = "github") -> str:
    """Count how many tools a Composio toolkit exposes.

    Fetches the public Composio tools directory page for the toolkit and
    extracts the number of tools from its embedded Next.js data / page text.

    Parameters:
        toolkit_slug: The Composio toolkit slug, e.g. "github", "slack", "gmail".
    """
    slug = toolkit_slug.strip().lower()

    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        resp = client.get(
            f"{COMPOSIO_API_BASE}/tools/{slug}",
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; composio-toolkit-tool/1.0)",
                "Accept": "text/html",
            },
        )
        resp.raise_for_status()
        html = resp.text

    result = {"toolkit": slug, "tool_count": None, "triggers_count": None}

    # The RSC payload embeds escaped JSON like: \"toolsCount\":846
    m = re.search(r'\\?"toolsCount\\?"\s*:\s*([0-9]+)', html)
    if m:
        result["tool_count"] = int(m.group(1))

    t = re.search(r'\\?"triggersCount\\?"\s*:\s*([0-9]+)', html)
    if t:
        result["triggers_count"] = int(t.group(1))

    # Fallback: count unique ACTION-style slugs (e.g. GITHUB_CREATE_ISSUE).
    if result["tool_count"] is None:
        prefix = slug.upper().replace("-", "_")
        slugs = set(re.findall(rf'\b{prefix}_[A-Z0-9_]+', html))
        if slugs:
            result["tool_count"] = len(slugs)

    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
