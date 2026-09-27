import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_debug_tool")

COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev")


@mcp.tool()
def probe(toolkit_slug: str = "github") -> str:
    """Fetch the Composio tools page and inspect action-slug patterns.

    Parameters:
        toolkit_slug: toolkit slug like 'github'.
    """
    slug = toolkit_slug.strip().lower()
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        resp = client.get(
            f"{COMPOSIO_API_BASE}/tools/{slug}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        )
        resp.raise_for_status()
        html = resp.text

    prefix = slug.upper().replace("-", "_")
    slugs = re.findall(rf'\b{prefix}_[A-Z0-9_]+', html)
    unique = sorted(set(slugs))

    out = {
        "unique_action_slugs": len(unique),
        "sample": unique[:10],
        "total_matches": len(matches) if (matches := slugs) else 0,
    }
    # look for words 'toolCount' style or 'tools' near numbers in escaped form
    kw = re.findall(r'\\?"[a-zA-Z_]*[Cc]ount\\?"\s*:\s*[0-9]+', html)
    out["count_keys"] = list(dict.fromkeys(kw))[:20]
    return json.dumps(out, indent=2)


if __name__ == "__main__":
    mcp.run()
