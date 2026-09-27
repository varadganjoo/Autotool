import os

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:50541/parcelly/api").rstrip("/")

mcp = FastMCP("parcelly_tracking_tool")


@mcp.tool()
def track_parcel(tracking_number: str = "PX-99812") -> str:
    """Fetch a parcel's tracking response from the Parcelly API.

    Args:
        tracking_number: Parcelly tracking number to look up, such as PX-99812.

    Returns:
        The API's JSON response text without changing its fields.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    with httpx.Client(timeout=10.0, auth=(username, password)) as client:
        response = client.get(f"{API_BASE}/track/{tracking_number}")
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
