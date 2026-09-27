import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_tracking_tool")
REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:61476/parcelly/api")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Fetch tracking status for a Parcelly shipment.

    Args:
        number: Parcel tracking number, such as PX-99812.
    """
    with httpx.Client(timeout=10, auth=(os.environ["PARCELLY_USERNAME"], os.environ["PARCELLY_PASSWORD"])) as client:
        response = client.get(f"{API_BASE}/track/{number}")
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
