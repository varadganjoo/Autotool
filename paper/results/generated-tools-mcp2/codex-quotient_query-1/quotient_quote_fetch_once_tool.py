import os
import json

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("quotient_quote_fetch_once_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53984/quotient/v1")


@mcp.tool()
def get_znth_latest_price() -> str:
    """Fetch the full ZNTH quote response from the Quotient market-data API."""
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": "ZNTH", "apikey": os.environ["QUOTIENT_API_KEY"]})
    if resp.status_code != 200:
        raise ToolError(f"Quotient API returned HTTP {resp.status_code} for symbol ZNTH")
    return json.dumps(resp.json())


if __name__ == "__main__":
    mcp.run()
