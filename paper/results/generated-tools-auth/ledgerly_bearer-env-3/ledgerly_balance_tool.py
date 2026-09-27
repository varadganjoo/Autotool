import json
import os
from decimal import Decimal
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:50541/ledgerly/v2").rstrip("/")

mcp = FastMCP("ledgerly_balance_tool")


@mcp.tool()
def get_account_balance(account_id: str) -> str:
    """Fetch an account's balance from Ledgerly and return its exact value in cents.

    Args:
        account_id: Ledgerly account identifier used in the balance endpoint path.
    """
    token = os.environ["LEDGERLY_TOKEN"]
    encoded_account_id = quote(account_id, safe="")
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/accounts/{encoded_account_id}/balance",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()

    payload = json.loads(response.text, parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError("Ledgerly balance response must be a JSON object")

    if "balance_cents" in payload:
        balance = payload["balance_cents"]
    elif "balance" in payload:
        balance = payload["balance"]
    else:
        raise ValueError("Ledgerly response does not contain a balance value")

    # Emit Decimal values as unquoted JSON numbers so large or fractional values
    # retain their exact representation instead of being rounded through float.
    if isinstance(balance, Decimal):
        if not balance.is_finite():
            raise ValueError("Ledgerly returned a non-finite balance")
        balance_json = str(balance)
    elif isinstance(balance, (int, float)) and not isinstance(balance, bool):
        balance_json = json.dumps(balance, allow_nan=False)
    else:
        balance_json = json.dumps(balance)

    return f'{{"balance_cents":{balance_json}}}'


if __name__ == "__main__":
    mcp.run()
