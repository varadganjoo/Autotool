import os
import json
import base64
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]

PARCELLY_API_BASE = os.environ.get("PARCELLY_API_BASE", "http://127.0.0.1:53984/parcelly/api")

mcp = MCPServer("parcelly_tracking_tool")


@mcp.tool()
def track(number: str) -> str:
    """Get the shipment status for a Parcelly tracking number.

    number: The parcel tracking number, e.g. PX-99812.
    """
    username = os.environ["PARCELLY_USERNAME"]
    password = os.environ["PARCELLY_PASSWORD"]
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    url = f"{PARCELLY_API_BASE}/track/{number}"
    try:
        resp = httpx2.get(
            url,
            headers={"Authorization": f"Basic {token}"},
            timeout=10.0,
        )
    except httpx2.HTTPError as e:
        raise ToolError(f"Parcelly request failed: {e}")
    if resp.status_code == 401:
        raise ToolError("Parcelly returned 401 Unauthorized: check credentials.")
    if resp.status_code == 404:
        raise ToolError(f"Parcelly returned 404: tracking number {number} not found.")
    if resp.status_code >= 400:
        raise ToolError(f"Parcelly returned status {resp.status_code}.")
    return resp.text


if __name__ == "__main__":
    mcp.run()
