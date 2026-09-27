import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:53933/ledgerly/v2").rstrip("/")
mcp = FastMCP("ledgerly_balance_tool")


@mcp.tool()
def account_balance(account_id: str) -> str:
    """Fetch an account balance, reported in euros.

    Args:
        account_id: Ledgerly account identifier, such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/accounts/{account_id}/balance",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        data = response.json()
    return json.dumps(data)


if __name__ == "__main__":
    mcp.run()
