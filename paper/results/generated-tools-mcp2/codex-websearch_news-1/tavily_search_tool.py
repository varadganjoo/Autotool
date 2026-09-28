import json
import os
from typing import Any

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = MCPServer("tavily_search_tool")
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_news(query: str, max_results: int = 5) -> str:
    """Search the web for recent news/articles and return titles, URLs, dates, and snippets.

    Args:
        query: Search query to send to Tavily.
        max_results: Maximum number of results to return, capped between 1 and 10.
    """
    limit = max(1, min(int(max_results), 10))
    payload: dict[str, Any] = {
        "query": query,
        "search_depth": "advanced",
        "topic": "news",
        "days": 30,
        "max_results": limit,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {
        "Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}",
        "Content-Type": "application/json",
    }
    with httpx2.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
    if resp.status_code != 200:
        raise ToolError(f"Tavily API returned HTTP {resp.status_code} for search")
    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise ToolError("Tavily API returned no results for search")
    simplified = []
    for item in results[:limit]:
        simplified.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "published_date": item.get("published_date"),
            "content": item.get("content"),
            "score": item.get("score"),
        })
    return json.dumps(simplified, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    mcp.run()
