import json
import os
from typing import Any

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["TAVILY_API_KEY"]
mcp = MCPServer("jwst_article_fetcher_tool")
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def get_three_jwst_articles() -> str:
    """Search the web for three recent James Webb Space Telescope articles and return titles and URLs."""
    payload: dict[str, Any] = {
        "query": "James Webb Space Telescope latest recent articles NASA JWST astronomy Webb telescope",
        "search_depth": "advanced",
        "topic": "news",
        "days": 30,
        "max_results": 8,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {
        "Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}",
        "Content-Type": "application/json",
    }
    with httpx2.Client(timeout=10) as client:
        resp = client.post(f"{TAVILY_API_BASE}/search", headers=headers, json=payload)
    if resp.status_code != 200:
        raise ToolError(f"Tavily API returned HTTP {resp.status_code} for JWST article search")
    data = resp.json()
    results = data.get("results", [])
    if len(results) < 3:
        raise ToolError("Tavily API returned fewer than three JWST article results")
    chosen = []
    seen_urls = set()
    for item in results:
        title = item.get("title")
        url = item.get("url")
        if not title or not url or url in seen_urls:
            continue
        chosen.append({"title": title, "url": url, "published_date": item.get("published_date")})
        seen_urls.add(url)
        if len(chosen) == 3:
            break
    if len(chosen) < 3:
        raise ToolError("Tavily API did not return three distinct titled JWST articles")
    return json.dumps(chosen, ensure_ascii=True, indent=2)


if __name__ == "__main__":
    mcp.run()
