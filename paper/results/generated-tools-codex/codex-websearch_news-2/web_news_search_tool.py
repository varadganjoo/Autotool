import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web_news_search_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_news(query: str, max_results: int = 5) -> str:
    """Search the web for recent news/articles and return titles, URLs, and dates when available.

    Args:
        query: Search query text.
        max_results: Maximum number of results to return.
    """
    payload = {
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": max(1, min(max_results, 10)),
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    simplified = []
    for item in data.get("results", []):
        simplified.append({
            "title": item.get("title"),
            "url": item.get("url"),
            "published_date": item.get("published_date"),
            "source": item.get("source"),
        })
    return json.dumps(simplified, ensure_ascii=True)


if __name__ == "__main__":
    mcp.run()
