import os
import json
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = MCPServer("tavily_search_tool")
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_web(query: str, max_results: int = 10) -> str:
    """Search the web for recent pages matching a query.

    Args:
        query: Search terms to send to Tavily.
        max_results: Maximum number of results, from 1 to 20.
    """
    if max_results < 1 or max_results > 20:
        raise ToolError("Tavily API requires max_results between 1 and 20")
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    with httpx2.Client(timeout=10) as client:
        resp = client.post(f"{API_BASE}/search", headers=headers, json=payload)
    if resp.status_code != 200:
        raise ToolError(f"Tavily API returned HTTP {resp.status_code}")
    data = resp.json()
    return json.dumps(data.get("results", []))


if __name__ == "__main__":
    mcp.run()
