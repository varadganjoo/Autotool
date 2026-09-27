import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")
mcp = FastMCP("web_search_tool")


@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web using Tavily.

    Args:
        query: Search terms to look up on the web.
        max_results: Maximum number of results to return (1-10).
    """
    if not 1 <= max_results <= 10:
        raise ValueError("max_results must be between 1 and 10")
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{API_BASE}/search",
            json={"api_key": os.environ["TAVILY_API_KEY"], "query": query, "max_results": max_results, "topic": "news"},
        )
        response.raise_for_status()
        data = response.json()
    return json.dumps(data.get("results", []))


if __name__ == "__main__":
    mcp.run()
