import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get(
    "PARCELLY_API_BASE",
    "http://127.0.0.1:50541/parcelly/api",
).rstrip("/")

mcp = FastMCP("parcelly_tracking_tool")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Query Parcelly tracking details for a parcel.

    Args:
        number: Parcelly tracking number to look up.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    url = f"{API_BASE}/track/{quote(number, safe='')}"

    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, auth=(username, password))
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            body = response.text

    return json.dumps(
        {"status_code": response.status_code, "body": body},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
