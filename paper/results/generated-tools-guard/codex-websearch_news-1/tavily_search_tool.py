import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tavily_search_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search(query: str, max_results: int = 5, days: int = 30) -> str:
    """Search the web with Tavily and return JSON results.

    Args:
        query: Search query text.
        max_results: Maximum number of results to return.
        days: Restrict news/recent search to this many days when supported.
    """
    payload = {
        "query": query,
        "max_results": max(1, min(max_results, 10)),
        "search_depth": "advanced",
        "topic": "news",
        "days": max(1, min(days, 365)),
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "published_date": item.get("published_date"),
            "source": item.get("source"),
            "score": item.get("score"),
        })
    return json.dumps(results, ensure_ascii=True)


if __name__ == "__main__":
    mcp.run()
