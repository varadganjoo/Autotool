import os
import json
import html
import re
from xml.etree import ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("news_search_tool")

REQUIRED_ENV = []

GOOGLENEWS_API_BASE = os.environ.get(
    "GOOGLENEWS_API_BASE", "https://news.google.com/rss"
)


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities from a string."""
    no_tags = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(no_tags).strip()


@mcp.tool()
def search_news(query: str, limit: int = 5) -> str:
    """Search recent news articles matching a query using the Google News RSS feed.

    Returns a JSON list of articles, each with 'title', 'url', 'source' and
    'published' fields, ordered from most to least recent.

    Parameters:
        query: The search terms, e.g. "James Webb Space Telescope".
        limit: Maximum number of articles to return (default 5).
    """
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{GOOGLENEWS_API_BASE}/search",
            params=params,
            headers={"User-Agent": "Mozilla/5.0 (news-search-tool)"},
        )
        response.raise_for_status()

    root = ET.fromstring(response.content)
    articles = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        source_el = item.find("source")
        source = source_el.text if source_el is not None else ""
        articles.append(
            {
                "title": _strip_html(title),
                "url": link.strip(),
                "source": _strip_html(source or ""),
                "published": pub.strip(),
            }
        )
        if len(articles) >= max(1, limit):
            break

    return json.dumps(articles, indent=2)


if __name__ == "__main__":
    mcp.run()
