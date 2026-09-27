import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_tracking_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:50541/parcelly/api")


@mcp.tool()
def track_shipment(tracking_number: str, username: str, password: str) -> str:
    """Request tracking information from Parcelly's local tracking API.

    Args:
        tracking_number: Shipment tracking number to look up.
        username: Username for HTTP Basic authentication.
        password: Password for HTTP Basic authentication.
    """
    encoded_tracking_number = quote(tracking_number, safe="")
    url = f"{API_BASE.rstrip('/')}/track/{encoded_tracking_number}"
    with httpx.Client(timeout=10) as client:
        response = client.get(url, auth=(username, password))

    try:
        body = response.json()
    except ValueError:
        body = response.text

    return json.dumps({"status_code": response.status_code, "body": body})


if __name__ == "__main__":
    mcp.run()
