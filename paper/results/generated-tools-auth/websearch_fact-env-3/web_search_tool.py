import json
import os
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("web_search_tool")
REQUIRED_ENV = ["TAVILY_API_KEY"]
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com").rstrip("/")


@mcp.tool()
def web_search(query: str) -> str:
    """Search the live web with Tavily and return concise, relevant results.

    Results include each page's title, URL, and a short content snippet. Official
    government, education, and selected international organization sources are
    placed first when present; Tavily's ranking orders results within each group.

    Args:
        query: The search query to send to Tavily.
    """
    api_key = os.environ["TAVILY_API_KEY"]
    payload = {
        "api_key": api_key,
        "query": query,
        "topic": "general",
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
    }

    with httpx.Client(timeout=10.0) as client:
        response = client.post(f"{API_BASE}/search", json=payload)
        response.raise_for_status()
        data = response.json()

    trusted_suffixes = (".gov", ".edu", "who.int", "un.org", "europa.eu", "w3.org")
    results = data.get("results", [])

    def is_authoritative(result: dict) -> bool:
        host = (urlsplit(result.get("url", "")).hostname or "").lower()
        return any(host == suffix.lstrip(".") or host.endswith("." + suffix.lstrip("."))
                   for suffix in trusted_suffixes)

    results = sorted(results, key=lambda item: not is_authoritative(item))
    concise_results = []
    for item in results:
        result = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": (item.get("content", "") or "")[:600],
        }
        published_date = item.get("published_date")
        if published_date:
            result["published_date"] = published_date
        concise_results.append(result)

    return json.dumps({"query": query, "results": concise_results}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
