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
def track_parcel(tracking_number: str) -> str:
    """Query Parcelly's tracking API for a shipment.

    Args:
        tracking_number: The shipment's tracking number.

    Returns the complete API response so status, last scan location, and any
    other fields are preserved even if the API uses different field names.
    """
    if not tracking_number.strip():
        raise ValueError("tracking_number must not be empty")

    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    url = f"{API_BASE}/track/{quote(tracking_number, safe='')}"

    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, auth=(username, password))
        response.raise_for_status()
        try:
            return json.dumps(response.json(), ensure_ascii=False)
        except ValueError:
            return response.text


if __name__ == "__main__":
    mcp.run()
