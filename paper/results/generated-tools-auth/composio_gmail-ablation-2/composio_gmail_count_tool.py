import json
import os
import re
from html.parser import HTMLParser
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("composio_gmail_count_tool")
COMPOSIO_API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://composio.dev")


class _PageParser(HTMLParser):
    """Collect visible text and links from the public toolkit page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.hrefs: list[str] = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.hrefs.append(value)


def _extract_count(text: str, html: str) -> tuple[int, str]:
    """Find a count explicitly stated in page text or its public page data."""
    normalized = re.sub(r"\s+", " ", text)
    patterns = (
        re.compile(r"\b(\d+)\s+(?:available\s+)?(?:tools|actions)\b", re.I),
        re.compile(r"\b(?:tools|actions)\s*\(\s*(\d+)\s*\)", re.I),
        re.compile(r"\b(?:tools|actions)\s*[:\-]\s*(\d+)\b", re.I),
        re.compile(r"\b(\d+)\s+(?:total\s+)?(?:tools|actions)\b", re.I),
    )
    for pattern in patterns:
        match = pattern.search(normalized)
        if match:
            start, end = match.span()
            return int(match.group(1)), normalized[max(0, start - 70):min(len(normalized), end + 70)].strip()

    # Some public toolkit pages include the same count in their embedded page data.
    data_patterns = (
        re.compile(r'"(?:actionCount|actionsCount|toolCount|toolsCount|totalActions|totalTools)"\s*:\s*(\d+)', re.I),
        re.compile(r"\b(?:actionCount|actionsCount|toolCount|toolsCount|totalActions|totalTools)\s*[:=]\s*(\d+)\b", re.I),
    )
    for pattern in data_patterns:
        match = pattern.search(html)
        if match:
            return int(match.group(1)), f"Public page data reports {match.group(1)} tools/actions."

    raise ValueError("Could not find an exact tools/actions count on the public Composio toolkit page.")


@mcp.tool()
def get_composio_toolkit_count(toolkit: str = "Gmail") -> str:
    """Retrieve a toolkit's tool/action count from Composio's public integrations page.

    Args:
        toolkit: Toolkit name to look up; defaults to Gmail. The name is converted
            to the public toolkit page slug (for example, "Google Calendar" becomes
            "google-calendar").

    Returns JSON containing the toolkit name, exact integer count, fetched source
    URL, and a short page excerpt or action-slug list when available.
    """
    name = toolkit.strip()
    if not name:
        raise ValueError("toolkit must be a non-empty name")

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    page_url = f"{COMPOSIO_API_BASE.rstrip('/')}/toolkits/{quote(slug, safe='-')}"
    with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "MCP public toolkit count lookup"}) as client:
        response = client.get(page_url)
        response.raise_for_status()

    parser = _PageParser()
    parser.feed(response.text)
    visible_text = " ".join(parser.text_parts)
    count, excerpt = _extract_count(visible_text, response.text)

    action_slugs: list[str] = []
    for href in parser.hrefs:
        match = re.search(r"/(?:actions|tools)/([^/?#]+)(?:[/?#]|$)", href, re.I)
        if match:
            action_slug = match.group(1).strip()
            if action_slug and action_slug not in action_slugs:
                action_slugs.append(action_slug)

    evidence: str = excerpt
    if action_slugs:
        evidence = json.dumps({"excerpt": excerpt, "action_slugs": action_slugs}, ensure_ascii=False)

    return json.dumps(
        {
            "toolkit": name,
            "tool_count": count,
            "source_url": str(response.url),
            "evidence": evidence,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
