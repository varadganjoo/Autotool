import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
mcp = FastMCP("parcelly_tracking_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:57311/parcelly/api")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Fetch shipment tracking status from Parcelly.

    Args:
        number: Parcelly shipment tracking number.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    with httpx.Client(timeout=10, auth=(username, password)) as client:
        response = client.get(f"{API_BASE.rstrip('/')}/track/{number}")
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
