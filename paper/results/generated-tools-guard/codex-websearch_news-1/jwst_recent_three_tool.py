import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jwst_recent_three_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search_nasa_latest() -> str:
    """Search NASA for recent JWST articles and return titles and URLs."""
    payload = {
        "query": "site:nasa.gov/webb James Webb Space Telescope article",
        "max_results": 5,
        "search_depth": "advanced",
        "topic": "news",
        "days": 180,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}", "Content-Type": "application/json"}
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    results = [{"title": r.get("title"), "url": r.get("url"), "published_date": r.get("published_date")} for r in data.get("results", [])]
    return json.dumps(results, ensure_ascii=True)


if __name__ == "__main__":
    mcp.run()
