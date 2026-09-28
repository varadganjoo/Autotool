import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:53984/parcelly/api").rstrip("/")
USERNAME = os.environ["PARCELLY_USERNAME"]
PASSWORD = os.environ["PARCELLY_PASSWORD"]

mcp = MCPServer("parcelly_tracking_tool")


@mcp.tool()
def track_shipment(number: str) -> str:
    """Fetch shipment tracking information from Parcelly.

    Args:
        number: Parcelly shipment tracking number.
    """
    with httpx2.Client(timeout=10, auth=(USERNAME, PASSWORD)) as client:
        response = client.get(f"{API_BASE}/track/{number}")
    if response.status_code != 200:
        raise ToolError(f"Parcelly API returned HTTP {response.status_code} for tracking number {number}")
    return response.text


if __name__ == "__main__":
    mcp.run()
