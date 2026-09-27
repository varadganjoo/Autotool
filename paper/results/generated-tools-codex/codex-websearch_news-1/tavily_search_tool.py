import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tavily_search_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search(query: str, max_results: int = 5, days: int = 30) -> str:
    """Search the web with Tavily and return recent result metadata as JSON.

    Args:
        query: Search query text.
        max_results: Maximum number of results to return.
        days: Limit news-style search recency to this many days where supported.
    """
    payload = {
        "query": query,
        "search_depth": "basic",
        "topic": "news",
        "max_results": max_results,
        "days": days,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    with httpx.Client(timeout=10) as client:
        response = client.post(f"{API_BASE}/search", headers=headers, json=payload)
        response.raise_for_status()
    data = response.json()
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "published_date": item.get("published_date"),
            "source": item.get("source"),
            "content": item.get("content"),
        })
    return json.dumps(results, indent=2)


if __name__ == "__main__":
    mcp.run()
