import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")

mcp = FastMCP("web_search_tool")


@mcp.tool()
def search_web(query: str, recency_days: int | None = None) -> str:
    """Search the live web for recent articles using Tavily.

    Args:
        query: Search terms describing the articles to find.
        recency_days: Optional number of days to restrict news results to. Must be positive.

    Returns up to 10 results as JSON, including each result's title, source URL,
    published date when available, and snippet.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if recency_days is not None and recency_days <= 0:
        raise ValueError("recency_days must be a positive integer")

    payload = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "topic": "news",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
    }
    if recency_days is not None:
        payload["days"] = recency_days

    with httpx.Client(timeout=10) as client:
        response = client.post(f"{API_BASE.rstrip('/')}/search", json=payload)
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("results", [])[:10]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "published_date": item.get("published_date") or item.get("published") or None,
                "snippet": item.get("content", ""),
            }
        )
    return json.dumps({"results": results}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
