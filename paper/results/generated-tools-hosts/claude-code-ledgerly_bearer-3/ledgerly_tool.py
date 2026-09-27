import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]

LEDGERLY_API_BASE = os.environ.get(
    "LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2"
)

mcp = FastMCP("ledgerly_tool")


@mcp.tool()
def account_balance(account_id: str) -> str:
    """Fetch the balance of a Ledgerly account.

    Calls GET /accounts/<account_id>/balance which returns the balance in
    cents. Returns a JSON object with the raw response, the balance in cents,
    and the balance converted to euros.

    Parameters:
        account_id: The Ledgerly account identifier, e.g. "ACC-4471".
    """
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{LEDGERLY_API_BASE}/accounts/{account_id}/balance"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    # The endpoint returns the balance in cents. Handle either a bare number
    # or an object containing a balance/balance_cents field.
    if isinstance(data, dict):
        cents = data.get("balance_cents", data.get("balance"))
    else:
        cents = data

    cents = int(cents)
    euros = cents / 100.0

    return json.dumps(
        {
            "account_id": account_id,
            "raw": data,
            "balance_cents": cents,
            "balance_euros": euros,
        }
    )


if __name__ == "__main__":
    mcp.run()
