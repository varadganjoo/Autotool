import json
import os
import re
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["TAVILY_API_KEY"]
TAVILY_API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com").rstrip("/")
NODEJS_API_BASE = os.environ.get("NODEJS_API_BASE", "https://nodejs.org").rstrip("/")

mcp = FastMCP("nodejs_release_lookup_tool")


@mcp.tool()
def lookup_latest_nodejs_release(query: str = "latest officially released Node.js version") -> str:
    """Search the web and verify the latest stable Node.js release against official data.

    Args:
        query: Optional web-search query. The official Node.js release index is always
            checked independently, so search results do not determine the version.
    """
    if len(query) > 500:
        raise ValueError("query must be 500 characters or fewer")

    api_key = os.environ["TAVILY_API_KEY"]
    search_query = query.strip() or "latest officially released Node.js version"
    if "node.js" not in search_query.lower() and "nodejs" not in search_query.lower():
        search_query += " Node.js latest official release"

    with httpx.Client(timeout=10.0) as client:
        search_response = client.post(
            f"{TAVILY_API_BASE}/search",
            json={
                "api_key": api_key,
                "query": search_query,
                "include_domains": ["nodejs.org"],
                "max_results": 5,
                "search_depth": "basic",
                "include_answer": False,
            },
        )
        search_response.raise_for_status()
        search_data = search_response.json()

        index_response = client.get(f"{NODEJS_API_BASE}/dist/index.json")
        index_response.raise_for_status()
        release_entries = index_response.json()

    if not isinstance(release_entries, list):
        raise ValueError("Official Node.js release index did not return a release list")

    stable_releases = []
    for entry in release_entries:
        if not isinstance(entry, dict):
            continue
        version = entry.get("version")
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version or "")
        if match:
            stable_releases.append((tuple(int(part) for part in match.groups()), entry))

    if not stable_releases:
        raise ValueError("No stable releases were found in the official Node.js index")

    _, latest = max(stable_releases, key=lambda item: item[0])
    latest_version = latest["version"]
    release_date = latest.get("date")

    source_urls = [
        f"{NODEJS_API_BASE}/dist/index.json",
        "https://nodejs.org/en/download",
    ]
    results = search_data.get("results", []) if isinstance(search_data, dict) else []
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if isinstance(url, str) and urlparse(url).hostname in {"nodejs.org", "www.nodejs.org"}:
                if url not in source_urls:
                    source_urls.append(url)

    date_text = f" dated {release_date}" if release_date else ""
    evidence_snippet = (
        f"The official Node.js distribution index lists {latest_version}{date_text}; "
        "this is the highest stable semantic version in that index."
    )
    return json.dumps(
        {
            "latest_version": latest_version,
            "release_date": release_date,
            "source_urls": source_urls,
            "evidence_snippet": evidence_snippet,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
