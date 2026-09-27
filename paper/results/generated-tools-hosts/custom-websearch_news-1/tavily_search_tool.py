import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = FastMCP("tavily_search_tool")
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web for recent articles.

    Args:
        query: Search query to send to the web search API.
        max_results: Maximum number of results to return, from 1 to 10.
    """
    if not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    payload = {"query": query, "max_results": max_results, "topic": "news", "time_range": "month"}
    with httpx.Client(timeout=10) as client:
        response = client.post(f"{API_BASE}/search", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    results = data.get("results", [])
    return json.dumps([{"title": item.get("title"), "url": item.get("url"), "published_date": item.get("published_date"), "content": item.get("content")} for item in results], ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
