import json
import os
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
import httpx2

mcp = MCPServer("news_search_tool")

HN_API_BASE = os.environ.get("HN_API_BASE", "https://hn.algolia.com/api/v1")


@mcp.tool()
def search_articles(query: str, limit: int = 5) -> str:
    """Search recent web articles/stories matching a query using the public
    Hacker News (Algolia) search API, sorted by most recent first.

    query: the search terms (e.g. 'James Webb Space Telescope').
    limit: maximum number of articles to return (default 5).
    Returns a JSON list of objects with 'title', 'url', and 'created_at'.
    """
    url = f"{HN_API_BASE}/search_by_date"
    params = {"query": query, "tags": "story", "hitsPerPage": max(1, min(limit * 3, 50))}
    try:
        with httpx2.Client(timeout=10) as client:
            resp = client.get(url, params=params)
    except httpx2.HTTPError as e:
        raise ToolError(f"Hacker News search request failed: {e}")

    if resp.status_code != 200:
        raise ToolError(f"Hacker News search returned status {resp.status_code}")

    data = resp.json()
    hits = data.get("hits", [])
    results = []
    for hit in hits:
        title = hit.get("title")
        link = hit.get("url")
        if not title or not link:
            continue
        results.append({
            "title": title,
            "url": link,
            "created_at": hit.get("created_at"),
        })
        if len(results) >= limit:
            break

    if not results:
        raise ToolError(f"No articles found for query: {query}")

    return json.dumps(results, indent=2)


if __name__ == "__main__":
    mcp.run()
