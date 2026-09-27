import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
mcp = FastMCP("quotient_market_tool")
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53933/quotient/v1")


@mcp.tool()
def latest_quote(symbol: str) -> str:
    """Get the latest market price for a ticker symbol.

    Args:
        symbol: Ticker symbol to query, such as ZNTH.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/quote",
            params={"symbol": symbol, "apikey": os.environ["QUOTIENT_API_KEY"]},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
