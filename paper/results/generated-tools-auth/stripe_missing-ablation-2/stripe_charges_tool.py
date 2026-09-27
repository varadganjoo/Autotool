import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stripe_charges_tool")
API_BASE = os.environ.get("STRIPE_API_BASE", "https://api.stripe.com")


@mcp.tool()
def get_recent_stripe_charges() -> str:
    """Report whether recent Stripe charges can be retrieved.

    No Stripe authorization is configured for this server, so it cannot access
    the account's private charges endpoint. It does not invent or return charge
    data when authorization is unavailable.
    """
    return "Stripe authorization is not configured; cannot retrieve charges from the Stripe account."


if __name__ == "__main__":
    mcp.run()
