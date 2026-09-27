import json
import os
from mcp.server.fastmcp import FastMCP

import httpx

REQUIRED_ENV = ["LEDGERLY_TOKEN"]

LEDGERLY_API_BASE = os.environ.get(
    "LEDGERLY_API_BASE", "http://127.0.0.1:53933/ledgerly/v2"
)

mcp = FastMCP("ledgerly_tool")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch the balance of a Ledgerly account.

    Calls GET /accounts/<account_id>/balance on the Ledgerly API, which
    returns the balance in cents. Returns the raw JSON response as a string
    along with the balance converted to euros.

    Parameters:
        account_id: The account identifier, e.g. "ACC-4471".
    """
    token = os.environ["LEDGERLY_TOKEN"]
    url = f"{LEDGERLY_API_BASE}/accounts/{account_id}/balance"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    result = {"raw": data}

    # Try to locate a cents value in the response
    cents = None
    if isinstance(data, (int, float)):
        cents = data
    elif isinstance(data, dict):
        for key in ("balance", "balance_cents", "cents", "amount"):
            if key in data and isinstance(data[key], (int, float)):
                cents = data[key]
                break

    if cents is not None:
        result["balance_cents"] = cents
        result["balance_euros"] = cents / 100.0

    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
