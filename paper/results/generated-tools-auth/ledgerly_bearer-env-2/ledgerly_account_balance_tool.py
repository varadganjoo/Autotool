import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_account_balance_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:50541/ledgerly/v2")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Get an account balance from Ledgerly.

    Args:
        account_id: Identifier of the account whose balance to retrieve.

    Returns the HTTP status and the exact JSON response body, including the
    balance amount in cents, without recalculating or modifying its fields.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    encoded_account_id = quote(account_id, safe="")
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/accounts/{encoded_account_id}/balance",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return json.dumps(
            {"status_code": response.status_code, "response": response.json()},
            ensure_ascii=False,
        )


if __name__ == "__main__":
    mcp.run()
