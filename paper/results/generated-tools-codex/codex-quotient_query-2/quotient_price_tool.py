import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_price_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:61476/quotient/v1")


@mcp.tool()
def get_latest_price(symbol: str) -> str:
    """Fetch only the latest price for a ticker symbol from the Quotient API.

    Args:
        symbol: Ticker symbol to request, such as ZNTH.
    """
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": symbol, "apikey": os.environ["QUOTIENT_API_KEY"]})
        resp.raise_for_status()
        data = resp.json()
    for key in ("price", "latestPrice", "latest_price", "last", "lastPrice", "close"):
        if isinstance(data, dict) and key in data:
            return json.dumps({"symbol": symbol, "price": data[key], "raw": data})
    return json.dumps({"symbol": symbol, "raw": data})


if __name__ == "__main__":
    mcp.run()
