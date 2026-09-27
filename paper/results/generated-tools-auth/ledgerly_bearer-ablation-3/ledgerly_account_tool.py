import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_account_tool")
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:50541/ledgerly/v2").rstrip("/")


@mcp.tool()
def get_account_balance(account_id: str, bearer_token: str = "") -> str:
    """Fetch an account's balance from Ledgerly.

    Returns the API's balance_cents value without converting or rounding it,
    along with the HTTP status and any API error. If no bearer token is
    supplied, reports that authentication is unavailable without making a request.

    Args:
        account_id: Ledgerly account identifier.
        bearer_token: Bearer token for Ledgerly. Leave empty if unavailable.
    """
    if not bearer_token:
        return json.dumps({
            "http_status": None,
            "balance_cents": None,
            "api_error": "Authentication is unavailable: no bearer token was supplied.",
        })

    url = f"{API_BASE}/accounts/{quote(account_id, safe='')}/balance"
    with httpx.Client(timeout=10) as client:
        response = client.get(
            url,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )

    payload = response.json()
    api_error = None
    balance_cents = None
    if isinstance(payload, dict):
        balance_cents = payload.get("balance_cents")
        api_error = payload.get("error")
        if api_error is None and not response.is_success:
            api_error = payload.get("message") or payload.get("detail")

    return json.dumps({
        "http_status": response.status_code,
        "balance_cents": balance_cents,
        "api_error": api_error,
        "response": payload,
    })


if __name__ == "__main__":
    mcp.run()
