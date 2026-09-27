import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jwst_recent_articles_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def get_jwst_articles(max_results: int = 6, days: int = 30) -> str:
    """Search for recent web articles about the James Webb Space Telescope.

    Args:
        max_results: Maximum number of results to return.
        days: Restrict news/recent search to this many days when supported.
    """
    payload = {
        "query": "recent articles James Webb Space Telescope JWST",
        "max_results": max(3, min(max_results, 10)),
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
        })
    return json.dumps(results, ensure_ascii=True)


if __name__ == "__main__":
    mcp.run()
