import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_api_tool")
API_BASE = os.environ.get(
    "LEDGERLY_API_BASE",
    "http://127.0.0.1:50541/ledgerly/v2",
).rstrip("/")
TOKEN_ENV = "LEDGERLY_API_TOKEN"


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch an account's balance from Ledgerly.

    Args:
        account_id: The Ledgerly account ID to look up.

    Returns the HTTP status and parsed JSON response. If LEDGERLY_API_TOKEN is
    set at runtime, it is sent as a Bearer token and is never included in the
    returned result.
    """
    headers = {}
    token = os.environ.get(TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    encoded_account_id = quote(account_id, safe="")
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{API_BASE}/accounts/{encoded_account_id}/balance",
            headers=headers,
        )
        return json.dumps(
            {
                "status_code": response.status_code,
                "response": response.json(),
            }
        )


if __name__ == "__main__":
    mcp.run()
