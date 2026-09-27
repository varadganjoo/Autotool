import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_tracking_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:50541/parcelly/api")


@mcp.tool()
def track_shipment(shipment_number: str, username: str, password: str) -> str:
    """Look up a Parcelly shipment using HTTP Basic authentication.

    Args:
        shipment_number: Shipment number to look up; used as one URL path segment.
        username: HTTP Basic authentication username. It is not included in the result.
        password: HTTP Basic authentication password. It is not included in the result.
    """
    encoded_number = quote(shipment_number, safe="")
    url = f"{API_BASE.rstrip('/')}/track/{encoded_number}"
    with httpx.Client(timeout=10) as client:
        response = client.get(url, auth=(username, password))

    result = {
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
    }
    try:
        result["response_json"] = response.json()
    except ValueError:
        result["response_text"] = response.text
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
