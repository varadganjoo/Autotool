import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_tool")
REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:53933/parcelly/api")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Fetch shipment tracking status from Parcelly.

    Args:
        number: Parcel tracking number, such as PX-99812.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/track/{number}", auth=(username, password))
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
