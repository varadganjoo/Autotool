import json
import os
from datetime import date

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nodejs_release_lookup_tool")
API_BASE = os.environ.get("NODEJS_API_BASE", "https://nodejs.org").rstrip("/")
SOURCE_URL = f"{API_BASE}/dist/index.json"


@mcp.tool()
def get_latest_nodejs_release() -> str:
    """Look up the newest Node.js release listed by the official release index.

    Returns the release version, ISO release date, source URL, and LTS or Current
    status when the official index provides enough information to determine it.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(SOURCE_URL)
        response.raise_for_status()
        releases = response.json()

    if not isinstance(releases, list):
        raise ValueError("The official Node.js release index did not contain a list")

    dated_releases = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        version = release.get("version")
        release_date = release.get("date")
        if not isinstance(version, str) or not isinstance(release_date, str):
            continue
        # Validate the official date and compare dates chronologically.
        parsed_date = date.fromisoformat(release_date)
        dated_releases.append((parsed_date, version, release))

    if not dated_releases:
        raise ValueError("No dated Node.js releases were present in the official index")

    _, version, latest = max(dated_releases, key=lambda item: item[0])
    lts_value = latest.get("lts")
    if isinstance(lts_value, str) and lts_value:
        release_type = "LTS"
    elif lts_value is False:
        release_type = "Current"
    else:
        release_type = "Unknown"

    result = {
        "version": version,
        "release_date": latest["date"],
        "source_url": SOURCE_URL,
        "release_type": release_type,
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
