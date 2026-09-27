import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]

PARCELLY_API_BASE = os.environ.get(
    "PARCELLY_API_BASE", "http://127.0.0.1:53933/parcelly/api"
)

mcp = FastMCP("parcelly_tracking_tool")


@mcp.tool()
def track(number: str) -> str:
    """Get the shipment status for a Parcelly tracking number.

    Calls GET /track/<number> on the Parcelly tracking API using HTTP Basic
    authentication with the account username and password.

    Args:
        number: The parcel tracking number, e.g. "PX-99812".
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]

    url = f"{PARCELLY_API_BASE}/track/{number}"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, auth=(username, password))
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
