import json
import os
import re
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com").rstrip("/")

mcp = FastMCP("nodejs_latest_version_tool")

_VERSION_RE = re.compile(r"\bv?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\b")


def _channel_near_version(text: str, start: int, end: int) -> str:
    """Return a release channel only when it is stated near the version."""
    context = text[max(0, start - 100):min(len(text), end + 100)]
    if re.search(r"\bLTS\b", context, re.IGNORECASE):
        return "LTS"
    if re.search(r"\bCurrent\b", context, re.IGNORECASE):
        return "Current"
    return "Not stated"


@mcp.tool()
def get_latest_nodejs_version() -> str:
    """Search authoritative Node.js web pages for the latest released version.

    The result is based on live Tavily search results restricted to nodejs.org.
    Returns the version, stated release channel, source URL, and supporting
    snippet and publication date when available. Raises an error if search
    results do not provide a version from an authoritative Node.js source.
    """
    api_key = os.environ["TAVILY_API_KEY"]
    payload = {
        "api_key": api_key,
        "query": "latest released Node.js version Current LTS site:nodejs.org/en/download OR site:nodejs.org/en/blog/release",
        "search_depth": "advanced",
        "topic": "general",
        "max_results": 8,
        "include_domains": ["nodejs.org"],
        "include_answer": False,
        "include_raw_content": False,
    }

    with httpx.Client(timeout=10) as client:
        response = client.post(f"{TAVILY_API_BASE}/search", json=payload)
        response.raise_for_status()
        data = response.json()

    results = data.get("results")
    if not isinstance(results, list):
        raise RuntimeError("Tavily search returned no usable results")

    for result in results:
        if not isinstance(result, dict):
            continue
        source_url = result.get("url")
        if not isinstance(source_url, str):
            continue
        hostname = (urlparse(source_url).hostname or "").lower()
        if hostname != "nodejs.org" and not hostname.endswith(".nodejs.org"):
            continue

        title = result.get("title") if isinstance(result.get("title"), str) else ""
        snippet = result.get("content") if isinstance(result.get("content"), str) else ""
        searchable_text = f"{title}\n{snippet}"
        match = _VERSION_RE.search(searchable_text)
        if not match:
            continue

        version = match.group(1)
        channel = _channel_near_version(searchable_text, match.start(), match.end())
        published_date = result.get("published_date")
        if not isinstance(published_date, str) or not published_date.strip():
            published_date = None

        support = snippet.strip() or title.strip()
        if len(support) > 500:
            support = support[:497].rstrip() + "..."

        return json.dumps(
            {
                "version": version,
                "release_channel": channel,
                "source_url": source_url,
                "supporting_snippet": support,
                "published_date": published_date,
            },
            ensure_ascii=False,
        )

    raise RuntimeError("Search results did not contain a Node.js version from nodejs.org")


if __name__ == "__main__":
    mcp.run()
