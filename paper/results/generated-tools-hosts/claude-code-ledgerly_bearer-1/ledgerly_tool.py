import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]

LEDGERLY_API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2")

mcp = FastMCP("ledgerly_tool")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch the balance for a Ledgerly account.

    Calls GET /accounts/<account_id>/balance on the Ledgerly v2 API using
    Bearer-token authentication. The raw API returns the balance in cents.
    This tool returns a JSON string with the raw response plus the balance
    converted to whole currency units (euros) for convenience.

    Parameters:
        account_id: The Ledgerly account identifier, e.g. "ACC-4471".
    """
    token = os.environ["LEDGERLY_TOKEN"]
    url = f"{LEDGERLY_API_BASE}/accounts/{account_id}/balance"
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    # The API returns the balance in cents; extract it robustly.
    balance_cents = None
    if isinstance(data, dict):
        for key in ("balance", "balance_cents", "cents", "value"):
            if key in data and isinstance(data[key], (int, float)):
                balance_cents = data[key]
                break
    elif isinstance(data, (int, float)):
        balance_cents = data

    result = {"account_id": account_id, "raw": data}
    if balance_cents is not None:
        result["balance_cents"] = balance_cents
        result["balance_euros"] = balance_cents / 100.0
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()
