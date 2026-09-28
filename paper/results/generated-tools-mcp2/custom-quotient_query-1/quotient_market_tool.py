import os
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
mcp = MCPServer("quotient_market_tool")
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53984/quotient/v1")

@mcp.tool()
def latest_quote(symbol: str) -> str:
    """Get the latest market price for a ticker from Quotient.

    Args:
        symbol: The ticker symbol to look up.
    """
    key = os.environ["QUOTIENT_API_KEY"]
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": key})
    if resp.status_code != 200:
        raise ToolError(f"Quotient API returned HTTP {resp.status_code} for symbol {symbol}")
    return resp.text

if __name__ == "__main__":
    mcp.run()
