import json
import os
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quotient_quote_tool")
REQUIRED_ENV = ["QUOTIENT_API_KEY"]
API_BASE_ENV = "QUOTIENT_API_BASE"
DEFAULT_API_BASE = "http://127.0.0.1:50541/quotient/v1"
_MISSING = object()


def _normalized_key(key: Any) -> str:
    """Normalize a response key for flexible matching."""
    return "".join(character.lower() for character in str(key) if character.isalnum())


def _find_price(value: Any) -> Any:
    """Find a current/latest price value in common quote response shapes."""
    preferred = {
        "latestprice", "currentprice", "lastprice", "regularmarketprice",
        "marketprice", "price", "05price", "close", "closingprice",
        "last", "current", "latest", "c", "p",
    }

    if isinstance(value, dict):
        # Check explicitly named price fields before descending into wrapper objects.
        items = list(value.items())
        items.sort(
            key=lambda pair: (
                0 if _normalized_key(pair[0]) in preferred
                else 1 if "price" in _normalized_key(pair[0])
                else 2 if "latest" in _normalized_key(pair[0]) or "current" in _normalized_key(pair[0])
                else 3
            )
        )
        for key, item in items:
            name = _normalized_key(key)
            is_price_key = (
                name in preferred
                or "price" in name
                or ("latest" in name and "current" in name)
            )
            if is_price_key:
                if isinstance(item, (dict, list)):
                    nested = _find_price(item)
                    if nested is not _MISSING:
                        return nested
                else:
                    return item
        for item in value.values():
            found = _find_price(item)
            if found is not _MISSING:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_price(item)
            if found is not _MISSING:
                return found
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return _MISSING


def _single_numeric_fallback(value: Any) -> Any:
    """Use a lone numeric data value when an API uses an undocumented field name."""
    ignored = {
        "symbol", "ticker", "name", "exchange", "timestamp", "time", "date",
        "volume", "sharesoutstanding", "marketcap", "change", "changepercent",
    }
    candidates = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if _normalized_key(key) not in ignored:
                    visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            candidates.append(node)
        elif isinstance(node, str) and re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", node):
            candidates.append(node)

    visit(value)
    return candidates[0] if len(candidates) == 1 else _MISSING


@mcp.tool()
def get_quote(symbol: str) -> str:
    """Fetch a ticker quote and return its latest price value.

    Args:
        symbol: Ticker symbol to look up, such as "AAPL".

    Returns:
        The latest price value serialized as JSON. HTTP failures include status details.
    """
    api_key = os.environ["QUOTIENT_API_KEY"]
    api_base = os.environ.get(API_BASE_ENV, DEFAULT_API_BASE).rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{api_base}/quote",
                params={"symbol": symbol, "apikey": api_key},
            )
    except httpx.HTTPError as exc:
        # Do not include the request URL, since the API key is sent as a query parameter.
        raise RuntimeError(f"Quote API request failed ({type(exc).__name__}).") from None

    if not response.is_success:
        raise RuntimeError(
            f"Quote API returned HTTP {response.status_code} {response.reason_phrase}."
        )

    data = response.json()
    latest_price = _find_price(data)
    if latest_price is _MISSING:
        latest_price = _single_numeric_fallback(data)
    if latest_price is _MISSING:
        raise KeyError("Quote API response did not contain a recognizable latest price value.")
    return json.dumps(latest_price, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
