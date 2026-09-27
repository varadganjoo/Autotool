import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:61476/quotient/v1")


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Fetch the latest market quote for a ticker symbol from the Quotient API.

    Args:
        symbol: Ticker symbol to request, such as ZNTH.
    """
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": os.environ["QUOTIENT_API_KEY"]})
        resp.raise_for_status()
        return resp.text


if __name__ == "__main__":
    mcp.run()
