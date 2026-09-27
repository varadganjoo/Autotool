import json
import os
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com").rstrip("/")

mcp = FastMCP("web_search_tool")


def _publication_timestamp(value: object) -> float | None:
    """Parse a publication date into a sortable timestamp, if available."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


@mcp.tool()
def search_web(query: str, recency_days: int | None = None) -> str:
    """Search recent web and news articles and return up to three results.

    Args:
        query: Search terms, such as "James Webb Space Telescope discoveries".
        recency_days: Optional number of recent days to limit news results to; must be positive.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    if recency_days is not None and recency_days < 1:
        raise ValueError("recency_days must be a positive integer")

    payload: dict[str, object] = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": 10,
        "include_answer": False,
        "include_raw_content": False,
    }
    if recency_days is not None:
        payload["days"] = recency_days

    with httpx.Client(timeout=10) as client:
        response = client.post(f"{TAVILY_API_BASE}/search", json=payload)
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])
    if not isinstance(results, list):
        raise ValueError("Tavily returned an invalid results field")

    # Prefer results with the newest available publication dates, using Tavily's
    # relevance score as a tie-breaker and for results without a publication date.
    def ranking(item: object) -> tuple[bool, float, float]:
        if not isinstance(item, dict):
            return (False, 0.0, 0.0)
        published = _publication_timestamp(item.get("published_date"))
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return (published is not None, published or 0.0, score)

    results.sort(key=ranking, reverse=True)
    formatted = []
    for item in results[:3]:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or ""
        formatted.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "publication_date": item.get("published_date"),
                "snippet": str(content).strip()[:500],
            }
        )

    return json.dumps(formatted, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
