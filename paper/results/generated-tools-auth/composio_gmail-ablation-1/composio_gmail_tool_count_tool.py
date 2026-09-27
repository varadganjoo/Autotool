import html
import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_gmail_tool_count_tool")
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev").rstrip("/")
GMAIL_TOOLKIT_URL = f"{COMPOSIO_API_BASE}/toolkits/gmail"
TOOL_ID_PATTERN = re.compile(r"\bGMAIL_[A-Z0-9]+(?:_[A-Z0-9]+)*\b", re.IGNORECASE)


@mcp.tool()
def get_gmail_tool_count() -> str:
    """Retrieve the current Gmail toolkit tool count from Composio's public toolkit page.

    This fetches the live page and counts distinct Gmail tool identifiers present in
    its source. It raises an error if the page cannot be fetched or contains no
    identifiable Gmail tool entries rather than guessing a count.

    Returns:
        A JSON string containing tool_count, source_url, and evidence.
    """
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(
            GMAIL_TOOLKIT_URL,
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()

    page_source = html.unescape(response.text)
    tool_ids = sorted({match.upper() for match in TOOL_ID_PATTERN.findall(page_source)})
    if not tool_ids:
        raise ValueError(
            "The live Composio Gmail toolkit page contained no identifiable Gmail tool entries."
        )

    result = {
        "tool_count": len(tool_ids),
        "source_url": str(response.url),
        "evidence": (
            f"Fetched the live Composio Gmail toolkit page and counted "
            f"{len(tool_ids)} distinct GMAIL_-prefixed tool identifiers in its source."
        ),
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
