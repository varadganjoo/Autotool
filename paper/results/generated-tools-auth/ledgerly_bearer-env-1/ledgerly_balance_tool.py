import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get(
    "LEDGERLY_API_BASE", "http://127.0.0.1:50541/ledgerly/v2"
).rstrip("/")

mcp = FastMCP("ledgerly_balance_tool")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch an account's balance from the Ledgerly accounting API.

    Args:
        account_id: The account identifier used in the Ledgerly balance endpoint.

    Returns:
        The response body as provided by the API, preserving its balance amount,
        currency, and any other response fields.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    encoded_account_id = quote(account_id, safe="")
    url = f"{API_BASE}/accounts/{encoded_account_id}/balance"

    with httpx.Client(timeout=10) as client:
        response = client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
