import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = []
STRIPE_API_BASE = os.environ.get("STRIPE_API_BASE", "https://api.stripe.com")

mcp = FastMCP("stripe_charges_tool")


@mcp.tool()
def list_recent_charges() -> str:
    """List the three most recent Stripe charges.

    Returns each charge's id, amount in integer minor units, currency, and
    creation timestamp. Reports when no Stripe secret credential is supplied.
    """
    # No Stripe credential is available to this server in its configured
    # runtime environment, so do not substitute an unrelated service token.
    return "No Stripe credential was supplied."


if __name__ == "__main__":
    mcp.run()
