import os
import json
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
LEDGERLY_API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:53984/ledgerly/v2")

mcp = MCPServer("ledgerly_tool")


@mcp.tool()
def account_balance(account_id: str) -> str:
    """Fetch the balance of a Ledgerly account.

    Calls GET /accounts/<account_id>/balance on the Ledgerly v2 API using
    Bearer-token authentication. Returns the raw JSON response, which
    includes the balance in cents.

    account_id: The Ledgerly account identifier, e.g. "ACC-4471".
    """
    token = os.environ["LEDGERLY_TOKEN"]
    url = f"{LEDGERLY_API_BASE}/accounts/{account_id}/balance"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx2.get(url, headers=headers, timeout=10.0)
    except httpx2.HTTPError as exc:
        raise ToolError(f"Ledgerly request failed: {exc}")
    if resp.status_code != 200:
        raise ToolError(
            f"Ledgerly returned HTTP {resp.status_code} for account {account_id}"
        )
    return resp.text


if __name__ == "__main__":
    mcp.run()
