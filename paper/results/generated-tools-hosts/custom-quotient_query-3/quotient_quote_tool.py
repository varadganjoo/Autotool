import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:57311/quotient/v1")
API_KEY = os.environ["QUOTIENT_API_KEY"]
mcp = FastMCP("quotient_quote_tool")


@mcp.tool()
def get_latest_quote(symbol: str) -> str:
    """Get the latest market price for a ticker from Quotient.

    Args:
        symbol: Ticker symbol to look up, such as ZNTH.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": API_KEY})
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
