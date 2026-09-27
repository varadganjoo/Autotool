import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
mcp = FastMCP("parcelly_tracking_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:57311/parcelly/api").rstrip("/")
USERNAME = os.environ["PARCELLY_USERNAME"]
PASSWORD = os.environ["PARCELLY_PASSWORD"]


@mcp.tool()
def track_parcel(number: str) -> str:
    """Look up the latest shipment tracking information.

    Args:
        number: Parcelly tracking number, such as PX-99812.
    """
    with httpx.Client(timeout=10, auth=(USERNAME, PASSWORD)) as client:
        response = client.get(f"{API_BASE}/track/{number}")
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
