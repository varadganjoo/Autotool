import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["QUOTIENT_API_KEY"]

QUOTIENT_API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:57311/quotient/v1")

mcp = FastMCP("quotient_tool")


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Get the latest price quote for a ticker symbol from the Quotient market-data API.

    symbol: The ticker symbol to look up (e.g. 'ZNTH').
    """
    apikey = os.environ["QUOTIENT_API_KEY"]
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{QUOTIENT_API_BASE}/quote",
            params={"symbol": symbol, "apikey": apikey},
        )
        response.raise_for_status()
        return json.dumps(response.json())


if __name__ == "__main__":
    mcp.run()
