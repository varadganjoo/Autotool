import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:53984/ledgerly/v2")

mcp = MCPServer("ledgerly_balance_tool")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch an account balance from Ledgerly, returned in cents.

    Args:
        account_id: Ledgerly account identifier, such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    with httpx2.Client(timeout=10) as client:
        resp = client.get(
            f"{API_BASE}/accounts/{account_id}/balance",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise ToolError(f"Ledgerly API returned HTTP {resp.status_code} for account {account_id}")
    return resp.text


if __name__ == "__main__":
    mcp.run()
