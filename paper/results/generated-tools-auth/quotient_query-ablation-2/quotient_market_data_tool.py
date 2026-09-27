import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_market_data_tool")
API_BASE = os.environ.get(
    "QUOTIENT_API_BASE",
    "http://127.0.0.1:50541/quotient/v1",
).rstrip("/")


@mcp.tool()
def get_quotient_quote(symbol: str = "ZNTH", api_key: str = "") -> str:
    """Fetch a quote from the local Quotient market-data API.

    Args:
        symbol: Market symbol to request; defaults to ZNTH.
        api_key: API key for the required `apikey` query parameter. If omitted,
            the tool reports that a key is unavailable and does not make a request.
    """
    if not api_key.strip():
        return json.dumps({
            "error": "No API key is available. Provide an API key to request a quote.",
            "symbol": symbol,
        })

    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/quote",
            params={"symbol": symbol, "apikey": api_key},
        )
        response.raise_for_status()
        try:
            response_fields = response.json()
        except ValueError:
            response_fields = response.text

        return json.dumps({
            "http_status": response.status_code,
            "response": response_fields,
        })


if __name__ == "__main__":
    mcp.run()
