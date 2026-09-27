import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")

mcp = FastMCP("web_search_tool")


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the live web for recent articles matching a query.

    Args:
        query: Search terms describing the articles to find.
        max_results: Maximum number of results to return, from 1 to 20.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if not 1 <= max_results <= 20:
        raise ValueError("max_results must be between 1 and 20")

    payload = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "topic": "news",
        "time_range": "week",
        "max_results": max_results,
    }
    with httpx.Client(timeout=10) as client:
        response = client.post(f"{TAVILY_API_BASE.rstrip('/')}/search", json=payload)
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("results", []):
        result = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
        }
        if item.get("published_date") is not None:
            result["published_date"] = item["published_date"]
        result["snippet"] = item.get("content", item.get("snippet", ""))
        results.append(result)

    return json.dumps(results, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
