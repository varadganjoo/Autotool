import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_tool")

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
LEDGERLY_API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2")


@mcp.tool()
def account_balance(account_id: str) -> str:
    """Fetch the balance of a Ledgerly account and return it in both cents and euros.

    account_id: The account identifier, e.g. "ACC-4471".
    """
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{LEDGERLY_API_BASE}/accounts/{account_id}/balance"
    with httpx.Client(timeout=10.0) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # The endpoint returns the balance in cents. Handle a few common shapes.
    if isinstance(data, dict):
        cents = data.get("balance", data.get("balance_cents", data.get("cents")))
    else:
        cents = data

    cents = int(cents)
    euros = cents / 100.0
    return json.dumps({
        "account_id": account_id,
        "balance_cents": cents,
        "balance_euros": euros,
        "raw": data,
    })


if __name__ == "__main__":
    mcp.run()
