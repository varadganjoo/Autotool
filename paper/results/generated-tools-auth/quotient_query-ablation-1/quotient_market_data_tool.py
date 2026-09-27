import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_market_data_tool")
API_BASE = os.environ.get("QUOTIENT_API_BASE", "http://127.0.0.1:50541/quotient/v1").rstrip("/")
QUOTIENT_API_KEY_ENV_NAMES = ["QUOTIENT_API_KEY", "API_KEY"]


def _configured_api_key() -> str | None:
    """Return the first configured Quotient API key, if one is available."""
    for name in QUOTIENT_API_KEY_ENV_NAMES:
        try:
            return os.environ[name]
        except KeyError:
            continue
    return None


@mcp.tool()
def get_quote(symbol: str, apikey: str | None = None) -> str:
    """Fetch a market quote for a ticker symbol from the Quotient API.

    Args:
        symbol: Ticker symbol to query, such as "AAPL".
        apikey: Optional API key. If omitted, use a configured QUOTIENT_API_KEY
            or API_KEY environment variable when available; otherwise query
            without an API key.
    """
    key = apikey if apikey is not None else _configured_api_key()
    params = {"symbol": symbol}
    if key:
        params["apikey"] = key

    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/quote", params=params)

    response_json = response.json()
    result = {
        "http_status": response.status_code,
        "response_json": response_json,
    }
    if isinstance(response_json, dict) and "price" in response_json:
        result["price"] = response_json["price"]
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
