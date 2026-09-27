import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_quote_lookup_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:61476/quotient/v1")


@mcp.tool()
def znth_latest_price() -> str:
    """Fetch the latest price for ZNTH from the Quotient market-data API."""
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/quote", params={"symbol": "ZNTH", "apikey": os.environ["QUOTIENT_API_KEY"]})
        response.raise_for_status()
        data = response.json()
        return json.dumps(data)


if __name__ == "__main__":
    mcp.run()
