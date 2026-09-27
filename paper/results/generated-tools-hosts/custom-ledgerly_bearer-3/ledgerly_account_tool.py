import os
import json
from urllib.parse import quote
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
mcp = FastMCP("ledgerly_account_tool")
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:57311/ledgerly/v2").rstrip("/")


@mcp.tool()
def account_balance_euros(account_id: str) -> str:
    """Fetch an account balance and return the API's balance response.

    Args:
        account_id: The Ledgerly account identifier, such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/{quote(account_id, safe='')}/balance", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
