import os
import json
import re
import html
from xml.etree import ElementTree

import httpx

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("news_search_tool")

GOOGLENEWS_API_BASE = os.environ.get(
    "GOOGLENEWS_API_BASE", "https://news.google.com"
)


def _strip_tags(text: str) -> str:
    """Remove HTML tags and unescape entities from a string."""
    no_tags = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(no_tags).strip()


@mcp.tool()
def search_news(query: str, limit: int = 5) -> str:
    """Search recent web news articles for a query using the public Google News RSS feed.

    Returns a JSON list of articles, each with 'title', 'url', 'source' and 'published'.

    Parameters:
        query: The search terms, e.g. "James Webb Space Telescope".
        limit: Maximum number of articles to return (default 5).
    """
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    url = f"{GOOGLENEWS_API_BASE}/rss/search"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (news-search-tool)"},
        )
        response.raise_for_status()

    root = ElementTree.fromstring(response.content)
    items = root.findall(".//item")

    results = []
    for item in items[: max(0, limit)]:
        title_el = item.find("title")
        link_el = item.find("link")
        source_el = item.find("source")
        date_el = item.find("pubDate")
        results.append(
            {
                "title": _strip_tags(title_el.text) if title_el is not None else "",
                "url": link_el.text.strip() if link_el is not None and link_el.text else "",
                "source": source_el.text.strip() if source_el is not None and source_el.text else "",
                "published": date_el.text.strip() if date_el is not None and date_el.text else "",
            }
        )

    return json.dumps(results, indent=2)


if __name__ == "__main__":
    mcp.run()
