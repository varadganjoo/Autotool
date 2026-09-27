import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
mcp = FastMCP("ledgerly_balance_tool")
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2").rstrip("/")
TOKEN = os.environ["LEDGERLY_TOKEN"]


@mcp.tool()
def account_balance_euros(account_id: str) -> str:
    """Fetch an account balance and express it in euros.

    Args:
        account_id: Ledgerly account identifier, such as ACC-4471.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/{account_id}/balance", headers={"Authorization": f"Bearer {TOKEN}"})
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
