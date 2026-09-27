import json
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nodejs_release_lookup_tool")
API_BASE = os.environ.get("NODEJS_API_BASE", "https://nodejs.org/dist")
VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


@mcp.tool()
def get_latest_nodejs_release() -> str:
    """Look up the latest stable Node.js release from the official release index.

    Returns the release version, release date when available, and exact URL of
    the official index queried. Prereleases and nightly builds are excluded.
    """
    source_url = f"{API_BASE.rstrip('/')}/index.json"
    with httpx.Client(timeout=10) as client:
        response = client.get(source_url)
        response.raise_for_status()
        releases = response.json()

    if not isinstance(releases, list):
        raise ValueError("The official Node.js release index did not contain a list.")

    stable_releases = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        version = release.get("version")
        if not isinstance(version, str):
            continue
        match = VERSION_PATTERN.fullmatch(version)
        if match:
            stable_releases.append((tuple(int(part) for part in match.groups()), release))

    if not stable_releases:
        raise ValueError("No stable releases were found in the official Node.js release index.")

    _, latest = max(stable_releases, key=lambda item: item[0])
    result = {
        "version": latest["version"],
        "release_date": latest.get("date"),
        "source_url": source_url,
    }
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
