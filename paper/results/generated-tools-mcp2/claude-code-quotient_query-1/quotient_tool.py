import os
import json
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
QUOTIENT_API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53984/quotient/v1")

mcp = MCPServer("quotient_tool")


@mcp.tool()
def quote(symbol: str) -> str:
    """Get the latest price for a ticker symbol from the Quotient market-data API.

    symbol: the ticker symbol to look up (e.g. 'ZNTH').
    """
    apikey = os.environ["QUOTIENT_API_KEY"]
    url = f"{QUOTIENT_API_BASE}/quote"
    try:
        resp = httpx2.get(url, params={"symbol": symbol, "apikey": apikey}, timeout=10.0)
    except Exception as e:
        raise ToolError(f"Quotient request failed: {e}")
    if resp.status_code != 200:
        raise ToolError(f"Quotient API returned status {resp.status_code} for symbol {symbol}")
    return resp.text


if __name__ == "__main__":
    mcp.run()
