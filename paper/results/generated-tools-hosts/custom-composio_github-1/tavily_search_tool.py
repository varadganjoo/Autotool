import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")
mcp = FastMCP("tavily_search_tool")

@mcp.tool()
def search_web(query: str, max_results: int = 5) -> str:
    """Search the web for current information.

    Args:
        query: Search terms to look up.
        max_results: Maximum number of search results to return, from 1 to 10.
    """
    max_results = max(1, min(max_results, 10))
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"{API_BASE}/search",
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results, "search_depth": "basic"},
        )
        response.raise_for_status()
        return response.text

if __name__ == "__main__":
    mcp.run()
