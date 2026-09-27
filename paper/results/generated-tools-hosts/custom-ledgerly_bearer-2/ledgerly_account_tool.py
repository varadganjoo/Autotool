import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
mcp = FastMCP("ledgerly_account_tool")
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2")
TOKEN = os.environ["LEDGERLY_TOKEN"]


@mcp.tool()
def account_balance(account_id: str) -> str:
    """Get an account balance from Ledgerly and convert cents to euros.

    Args:
        account_id: Ledgerly account identifier, such as ACC-4471.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/accounts/{account_id}/balance",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        response.raise_for_status()
        data = response.json()
    if isinstance(data, dict):
        value = data.get("balance", data.get("balance_cents"))
    else:
        value = data
    if value is None:
        raise ValueError("API response did not contain a balance")
    cents = int(value)
    euros = cents / 100
    return f"{euros:.2f} EUR (balance: {cents} cents)"


if __name__ == "__main__":
    mcp.run()
