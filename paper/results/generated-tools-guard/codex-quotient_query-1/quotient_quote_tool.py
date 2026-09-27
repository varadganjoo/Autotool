import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_quote_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:53933/quotient/v1")


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Fetch the latest market quote for a ticker symbol from the Quotient API.

    Args:
        symbol: Ticker symbol to query, such as ZNTH.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": os.environ["QUOTIENT_API_KEY"]})
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
