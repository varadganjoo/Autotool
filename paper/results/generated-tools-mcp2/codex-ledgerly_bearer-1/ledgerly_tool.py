import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("ledgerly_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:53984/ledgerly/v2")


@mcp.tool()
def get_account_balance_euros(account_id: str) -> str:
    """Fetch the Ledgerly account balance and return it in euros.

    Args:
        account_id: Ledgerly account identifier, such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    url = f"{API_BASE.rstrip('/')}/accounts/{account_id}/balance"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx2.Client(timeout=10) as client:
        resp = client.get(url, headers=headers)
    if resp.status_code != 200:
        raise ToolError(f"Ledgerly API returned HTTP {resp.status_code} for account {account_id}")
    text = resp.text.strip()
    try:
        cents = int(text)
    except ValueError:
        data = resp.json()
        if isinstance(data, dict):
            for key in ("balance", "balance_cents", "cents", "amount_cents"):
                if key in data:
                    cents = int(data[key])
                    break
            else:
                raise ToolError("Ledgerly API response did not include a recognized cents field")
        else:
            raise ToolError("Ledgerly API response was not a cents integer or object")
    return f"{cents / 100:.2f}"


if __name__ == "__main__":
    mcp.run()
