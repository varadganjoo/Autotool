import os
import json
import xml.etree.ElementTree as ET
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("news_search_tool")

GNEWS_API_BASE = os.environ.get("GNEWS_API_BASE", "https://news.google.com")


@mcp.tool()
def search_news(query: str, limit: int = 5) -> str:
    """Search recent news articles via Google News RSS and return titles, URLs, and sources.

    query: the search terms (e.g. 'James Webb Space Telescope').
    limit: maximum number of articles to return (default 5).
    """
    url = f"{GNEWS_API_BASE}/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title = item.findtext("title")
        link = item.findtext("link")
        pub = item.findtext("pubDate")
        source_el = item.find("source")
        source = source_el.text if source_el is not None else None
        items.append({"title": title, "url": link, "source": source, "published": pub})
        if len(items) >= limit:
            break
    return json.dumps(items, indent=2)


if __name__ == "__main__":
    mcp.run()
