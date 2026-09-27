import json
import os
import xml.etree.ElementTree as ET

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web_search_tool")
API_BASE = os.environ.get("GOOGLE_NEWS_API_BASE", "https://news.google.com/rss/search")


@mcp.tool()
def search_web(query: str, recency_days: int | None = 30) -> str:
    """Search Google News for recent articles matching a query.

    Args:
        query: Topic or keywords to search for. Must not be blank.
        recency_days: Limit results to articles from this many days. Use None
            to omit the recency filter; otherwise provide a positive number.

    Returns:
        JSON containing up to 10 results with title, URL, publisher, and
        published date when available. Values are taken from the RSS results.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if recency_days is not None and recency_days < 1:
        raise ValueError("recency_days must be positive or None")

    search_query = query.strip()
    if recency_days is not None:
        search_query = f"{search_query} when:{recency_days}d"

    params = {
        "q": search_query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    headers = {"User-Agent": "web_search_tool/1.0"}
    with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
        response = client.get(API_BASE, params=params)
        response.raise_for_status()

    root = ET.fromstring(response.content)
    results = []
    for item in root.findall("./channel/item")[:10]:
        source = item.find("source")
        results.append(
            {
                "title": item.findtext("title"),
                "url": item.findtext("link"),
                "publisher": source.text if source is not None else None,
                "published_date": item.findtext("pubDate"),
            }
        )
    return json.dumps(results, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
