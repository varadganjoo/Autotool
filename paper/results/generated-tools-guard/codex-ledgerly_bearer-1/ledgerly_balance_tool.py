import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_balance_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:53933/ledgerly/v2")


@mcp.tool()
def get_account_balance_euros(account_id: str) -> str:
    """Fetch an account balance from Ledgerly and return euros.

    Args:
        account_id: Ledgerly account id, for example ACC-4471.
    """
    headers = {"Authorization": f"Bearer {os.environ['LEDGERLY_TOKEN']}"}
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/accounts/{account_id}/balance", headers=headers)
        resp.raise_for_status()
        text = resp.text.strip()
    data = resp.json()
    if isinstance(data, dict):
        cents = data.get("balance")
        if cents is None:
            cents = data.get("balance_cents")
        if cents is None:
            cents = data.get("cents")
    else:
        cents = data
    return f"{int(cents) / 100:.2f}"


if __name__ == "__main__":
    mcp.run()
