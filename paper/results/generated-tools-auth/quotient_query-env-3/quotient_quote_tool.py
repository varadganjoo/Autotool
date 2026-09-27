import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:50541/quotient/v1")

mcp = FastMCP("quotient_quote_tool")


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Fetch a market quote for a ticker symbol.

    Args:
        symbol: Ticker symbol to look up, such as AAPL.
    """
    api_key = os.environ["QUOTIENT_API_KEY"]
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/quote",
            params={"symbol": symbol, "apikey": api_key},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
