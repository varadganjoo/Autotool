import os
import json

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("quotient_quote_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53984/quotient/v1")


@mcp.tool()
def get_latest_quote(symbol: str) -> str:
    """Fetch the latest quote for a ticker from the Quotient market-data API.

    Args:
        symbol: Ticker symbol to look up, such as ZNTH.
    """
    api_key = os.environ["QUOTIENT_API_KEY"]
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": api_key})
    if resp.status_code != 200:
        raise ToolError(f"Quotient API returned HTTP {resp.status_code} for symbol {symbol}")
    try:
        data = resp.json()
    except Exception as exc:
        raise ToolError(f"Quotient API returned non-JSON response for symbol {symbol}") from exc
    return json.dumps(data)


if __name__ == "__main__":
    mcp.run()
