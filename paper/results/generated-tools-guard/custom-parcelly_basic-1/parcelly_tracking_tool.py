import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
mcp = FastMCP("parcelly_tracking_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:53933/parcelly/api").rstrip("/")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Fetch current tracking status for a Parcelly shipment.

    Args:
        number: Parcelly shipment tracking number, such as PX-99812.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    with httpx.Client(timeout=10, auth=(username, password)) as client:
        response = client.get(f"{API_BASE}/track/{number}")
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
