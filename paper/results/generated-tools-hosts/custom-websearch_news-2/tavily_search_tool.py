import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = FastMCP("tavily_search_tool")
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web for recent articles matching a query.

    Args:
        query: The web search query.
        max_results: Maximum number of search results to return, from 1 to 10.
    """
    limit = max(1, min(max_results, 10))
    payload = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "topic": "news",
        "include_answer": False,
    }
    with httpx.Client(timeout=10) as client:
        response = client.post(f"{API_BASE.rstrip('/')}/search", json=payload)
        response.raise_for_status()
        data = response.json()
    results = data.get("results", [])
    return "\n".join(f"{item.get('title', '')}\t{item.get('url', '')}\t{item.get('published_date', '')}" for item in results)


if __name__ == "__main__":
    mcp.run()
