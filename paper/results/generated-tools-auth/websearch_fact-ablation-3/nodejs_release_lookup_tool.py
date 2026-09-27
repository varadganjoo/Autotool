import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nodejs_release_lookup_tool")
API_BASE = os.environ.get("NODEJS_API_BASE", "https://nodejs.org/dist").rstrip("/")


@mcp.tool()
def get_latest_nodejs_release() -> str:
    """Look up the latest stable Node.js release from the official release data.

    Returns the release version, release date, and URL of the release data source.
    Nightly and prerelease versions are excluded.
    """
    source_url = f"{API_BASE}/index.json"
    with httpx.Client(timeout=10) as client:
        response = client.get(source_url)
        response.raise_for_status()
        releases = response.json()

    if not isinstance(releases, list):
        raise ValueError("Node.js release data was not a JSON list")

    stable_releases = [
        release
        for release in releases
        if isinstance(release, dict)
        and isinstance(release.get("version"), str)
        and re.fullmatch(r"v\d+\.\d+\.\d+", release["version"])
        and isinstance(release.get("date"), str)
    ]
    if not stable_releases:
        raise ValueError("No stable Node.js releases were found")

    latest = max(stable_releases, key=lambda release: release["date"])
    return json.dumps(
        {
            "version": latest["version"],
            "release_date": latest["date"],
            "source_url": source_url,
        }
    )


if __name__ == "__main__":
    mcp.run()
