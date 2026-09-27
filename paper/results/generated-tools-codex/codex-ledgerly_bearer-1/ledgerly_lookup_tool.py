import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ledgerly_lookup_tool")
REQUIRED_ENV = ["LEDGERLY_TOKEN"]
API_BASE = os.environ.get("LEDGERLY_API_BASE", "http://127.0.0.1:61476/ledgerly/v2")


@mcp.tool()
def answer_acc_4471_balance() -> str:
    """Fetch ACC-4471 balance from Ledgerly and return the balance in euros."""
    token = os.environ["LEDGERLY_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/accounts/ACC-4471/balance", headers=headers)
        response.raise_for_status()
        raw = response.text.strip()
        try:
            cents = int(raw)
        except ValueError:
            data = response.json()
            if isinstance(data, dict):
                for key in ("balance", "balance_cents", "cents"):
                    if key in data:
                        cents = int(data[key])
                        break
                else:
                    raise ValueError("Ledgerly response did not contain a balance field")
            else:
                cents = int(data)
    return f"{cents / 100:.2f} EUR"


if __name__ == "__main__":
    mcp.run()
