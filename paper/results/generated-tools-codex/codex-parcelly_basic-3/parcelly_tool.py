import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]

mcp = FastMCP("parcelly_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:61476/parcelly/api")


@mcp.tool()
def track(number: str) -> str:
    """Fetch Parcelly shipment tracking status.

    Args:
        number: Parcel tracking number to look up.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    url = f"{API_BASE.rstrip('/')}/track/{number}"
    with httpx.Client(timeout=10) as client:
        response = client.get(url, auth=(username, password))
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
