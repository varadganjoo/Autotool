import json
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_euro_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:61476/ledgerly/v2")


@mcp.tool()
def get_account_balance_euros(account_id: str) -> str:
    """Fetch an account balance from Ledgerly and return it in euros.

    Args:
        account_id: Ledgerly account identifier such as ACC-4471.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/{account_id}/balance", headers=headers)
        response.raise_for_status()
    body = response.text.strip()
    try:
        parsed = response.json()
    except json.JSONDecodeError:
        cents = int(body)
    else:
        if isinstance(parsed, int):
            cents = parsed
        elif isinstance(parsed, dict):
            for key in ("balance", "balance_cents", "cents", "amount_cents"):
                if key in parsed:
                    cents = int(parsed[key])
                    break
            else:
                raise ValueError(f"No cent balance field found in Ledgerly response keys: {sorted(parsed.keys())}")
        else:
            raise ValueError(f"Unexpected Ledgerly response type: {type(parsed).__name__}")
    euros = cents / 100
    return json.dumps({"account_id": account_id, "balance_cents": cents, "balance_euros": f"{euros:.2f}"})


if __name__ == "__main__":
    mcp.run()
