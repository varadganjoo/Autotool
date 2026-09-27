import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_answer_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:61476/quotient/v1")


@mcp.tool()
def answer_znth_price() -> str:
    """Fetch the latest ZNTH price from the Quotient API and return it as plain text."""
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/quote", params={"symbol": "ZNTH", "apikey": os.environ["QUOTIENT_API_KEY"]})
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, dict):
        for key in ("price", "latestPrice", "latest_price", "last", "lastPrice", "close"):
            if key in data:
                return str(data[key])
    return str(data)


if __name__ == "__main__":
    mcp.run()
