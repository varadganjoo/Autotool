import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:61476/ledgerly/v2")


@mcp.tool()
def get_account_balance_euros(account_id: str) -> str:
    """Fetch an account balance from Ledgerly and return euros.

    Args:
        account_id: Ledgerly account id, such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/{account_id}/balance", headers=headers)
        response.raise_for_status()
        text = response.text.strip()
    try:
        cents = int(text)
    except ValueError:
        data = response.json()
        if isinstance(data, dict):
            value = data.get("balance") or data.get("balance_cents") or data.get("cents")
            cents = int(value)
        else:
            cents = int(data)
    return f"{cents / 100:.2f}"


if __name__ == "__main__":
    mcp.run()
