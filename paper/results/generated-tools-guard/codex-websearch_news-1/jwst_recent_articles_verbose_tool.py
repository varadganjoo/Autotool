import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jwst_recent_articles_verbose_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def get_jwst_articles() -> str:
    """Search for recent web articles about the James Webb Space Telescope and return the top results."""
    payload = {
        "query": "James Webb Space Telescope JWST recent article",
        "max_results": 8,
        "search_depth": "advanced",
        "topic": "news",
        "days": 90,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
        resp.raise_for_status()
        return json.dumps(resp.json().get("results", []), ensure_ascii=True)


if __name__ == "__main__":
    mcp.run()
