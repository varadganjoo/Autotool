import html
import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_gmail_tool_count_tool")
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev").rstrip("/")


def _extract_explicit_tool_counts(page: str) -> set[int]:
    """Find explicit tool-count fields or text in a toolkit page."""
    counts: set[int] = set()

    # Structured data is preferable to matching arbitrary numbers in the page.
    field_pattern = re.compile(
        r'["\'](?:tool_count|toolCount|tools_count|toolsCount|total_tools|totalTools)'
        r'["\']\s*:\s*["\']?(\d+)',
        re.IGNORECASE,
    )
    counts.update(int(match) for match in field_pattern.findall(page))

    # Check user-visible page text for an explicit count, not a count inferred
    # from a potentially partial list of rendered tool links.
    text = html.unescape(re.sub(r"<[^>]*>", " ", page))
    text_patterns = (
        re.compile(r"\b(\d+)\s+(?:available\s+)?tools\b", re.IGNORECASE),
        re.compile(r"\btools\s*[:(]\s*(\d+)\b", re.IGNORECASE),
    )
    for pattern in text_patterns:
        counts.update(int(match) for match in pattern.findall(text))

    return counts


@mcp.tool()
def get_gmail_tool_count() -> str:
    """Fetch the current exact number of tools in Composio's Gmail toolkit.

    The public Composio Gmail toolkit page is checked for an explicit tool
    count. The result includes the final page URL used as its source. If the
    page does not expose an unambiguous exact count, the tool raises an error
    rather than estimating from a possibly incomplete listing.
    """
    source_url = f"{COMPOSIO_API_BASE}/toolkits/gmail"
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        response = client.get(source_url, headers={"Accept": "text/html"})
        response.raise_for_status()

    counts = _extract_explicit_tool_counts(response.text)
    if len(counts) != 1:
        raise ValueError(
            "The Composio Gmail toolkit page did not provide one unambiguous explicit tool count."
        )

    return json.dumps(
        {
            "tool_count": counts.pop(),
            "source_url": str(response.url),
        }
    )


if __name__ == "__main__":
    mcp.run()
