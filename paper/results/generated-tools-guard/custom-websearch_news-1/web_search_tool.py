import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = FastMCP("web_search_tool")
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_recent_articles(query: str, max_results: int = 5) -> str:
    """Search the web for recent articles.

    Args:
        query: Search topic or keywords.
        max_results: Maximum number of article results to return, from 1 to 10.
    """
    if not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    payload = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "topic": "news",
        "days": 30,
        "max_results": max_results,
        "include_answer": False,
    }
    with httpx.Client(timeout=10) as client:
        response = client.post(f"{API_BASE}/search", json=payload)
        response.raise_for_status()
        data = response.json()
    results = data.get("results", [])
    return "\n".join(f"{item.get('title', '')}\t{item.get('url', '')}" for item in results)


if __name__ == "__main__":
    mcp.run()
