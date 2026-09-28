import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]

mcp = MCPServer("parcelly_tool")
API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:53984/parcelly/api")


@mcp.tool()
def track_parcel(number: str) -> str:
    """Fetch tracking information for a Parcelly shipment.

    Args:
        number: Parcel tracking number, such as PX-99812.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    url = f"{API_BASE.rstrip('/')}/track/{number}"
    with httpx2.Client(timeout=10) as client:
        resp = client.get(url, auth=(username, password))
    if resp.status_code != 200:
        raise ToolError(f"Parcelly API returned HTTP {resp.status_code} for tracking number {number}")
    return resp.text


if __name__ == "__main__":
    mcp.run()
