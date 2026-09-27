import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("news_search_tool")

HN_API_BASE = os.environ.get("HN_API_BASE", "https://hn.algolia.com/api/v1")


@mcp.tool()
def search_news(query: str, max_records: int = 5) -> str:
    """Search recent web articles matching a query using the Hacker News (Algolia) index.

    Results are ordered by most recent first and only include stories that link to
    an external article (each has a real title and URL).

    Args:
        query: The search query, e.g. "James Webb Space Telescope".
        max_records: Maximum number of articles to return (1-50).

    Returns a JSON string with a list of articles, each having title, url and created_at.
    """
    if max_records < 1:
        max_records = 1
    if max_records > 50:
        max_records = 50

    params = {
        "query": query,
        "tags": "story",
        "hitsPerPage": max_records * 4,
    }
    headers = {"User-Agent": "news-search-tool/1.0"}

    with httpx.Client(timeout=10.0) as client:
        response = client.get(f"{HN_API_BASE}/search_by_date", params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    articles = []
    for hit in data.get("hits", []):
        url = hit.get("url")
        title = hit.get("title")
        if not url or not title:
            continue
        articles.append(
            {
                "title": title,
                "url": url,
                "created_at": hit.get("created_at"),
            }
        )
        if len(articles) >= max_records:
            break

    return json.dumps({"count": len(articles), "articles": articles}, indent=2)


if __name__ == "__main__":
    mcp.run()
