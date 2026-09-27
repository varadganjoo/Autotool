import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:61476/ledgerly/v2")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch an account balance from Ledgerly.

    Args:
        account_id: Ledgerly account identifier such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/{account_id}/balance", headers=headers)
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
