import json
import os
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_quote_tool")

REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE = os.environ.get(
    "QUOTIENT_API_BASE", "http://127.0.0.1:50541/quotient/v1"
).rstrip("/")

PRICE_FIELDS = {
    "price",
    "latestprice",
    "latestquoteprice",
    "latesttradingprice",
    "currentprice",
    "regularmarketprice",
    "marketprice",
    "lastprice",
    "lasttradedprice",
    "lasttradeprice",
    "close",
    "05price",
    "c",
}
LATEST_WRAPPERS = {"latest", "latestquote", "quote", "data", "result"}
CURRENCY_FIELDS = {"currency", "currencycode"}


def normalize_key(key: Any) -> str:
    """Normalize a response field name for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def find_price(data: Any, in_quote_context: bool = False) -> Any:
    """Find a price field, including common price aliases in nested quote objects."""
    if isinstance(data, dict):
        # Prefer explicitly named price fields, including variants such as
        # latest_market_price or latestPriceUsd.
        for key, value in data.items():
            name = normalize_key(key)
            explicitly_price = (
                name in PRICE_FIELDS
                or "price" in name
                or name in {"05price", "last", "close"}
            )
            if explicitly_price and value is not None:
                if not isinstance(value, (dict, list)):
                    return value
                nested = find_price(value, in_quote_context=True)
                if nested is not None:
                    return nested

        for key, value in data.items():
            name = normalize_key(key)
            if name in LATEST_WRAPPERS:
                nested = find_price(value, in_quote_context=True)
                if nested is not None:
                    return nested
            else:
                nested = find_price(value, in_quote_context=in_quote_context)
                if nested is not None:
                    return nested

        # Some APIs place the scalar under `value` or `amount` inside a
        # latest/quote object rather than naming the field `price`.
        if in_quote_context:
            for key in ("value", "amount"):
                if key in data and data[key] is not None and not isinstance(
                    data[key], (dict, list)
                ):
                    return data[key]
    elif isinstance(data, list):
        for item in data:
            nested = find_price(item, in_quote_context=in_quote_context)
            if nested is not None:
                return nested
    return None


def find_currency(data: Any) -> Any:
    """Find a currency field in a nested API response."""
    if isinstance(data, dict):
        for key, value in data.items():
            if normalize_key(key) in CURRENCY_FIELDS and value is not None:
                return value
        for value in data.values():
            found = find_currency(value)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_currency(item)
            if found is not None:
                return found
    return None


def has_api_error(payload: Any) -> bool:
    """Return whether the response contains a conventional API error marker."""
    if isinstance(payload, dict):
        if payload.get("success") is False or str(payload.get("status", "")).lower() == "error":
            return True
        if payload.get("error") or payload.get("errors"):
            return True
        return any(has_api_error(value) for value in payload.values())
    if isinstance(payload, list):
        return any(has_api_error(item) for item in payload)
    return False


@mcp.tool()
def get_latest_quote(symbol: str) -> str:
    """Fetch a ticker's latest price and return it with currency and raw fields.

    Args:
        symbol: Ticker symbol to look up, such as "AAPL".

    Returns the API's price value without converting it, the currency when
    supplied, and the complete raw response. Raises an error for HTTP/API
    failures or when the response does not contain a recognizable price.
    """
    api_key = os.environ["QUOTIENT_API_KEY"]
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{API_BASE}/quote",
            params={"symbol": symbol, "apikey": api_key},
        )

    # Avoid exposing the API key, which is included in the query string, in errors.
    if response.is_error:
        raise RuntimeError(f"Quotient API returned HTTP {response.status_code}")

    payload: Any = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError("Quotient API returned an unexpected response format")
    if has_api_error(payload):
        raise RuntimeError("Quotient API reported an API error")

    latest_price = find_price(payload)
    if latest_price is None:
        raise ValueError("Quotient API response did not include a recognizable latest price")

    result: dict[str, Any] = {
        "latest_price": latest_price,
        "raw_response": payload,
    }
    currency = find_currency(payload)
    if currency is not None:
        result["currency"] = currency
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
