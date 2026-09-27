from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stripe_charges_tool")


@mcp.tool()
def get_recent_stripe_charges() -> str:
    """Fetch the authenticated user's three most recent Stripe charges.

    This runtime has no Stripe credentials or connected Stripe integration, so
    it cannot make the authenticated request required to retrieve charges.
    Returns a clear error message rather than fabricated charge data.
    """
    return (
        "Stripe charges are unavailable: no Stripe credentials or connected "
        "integration are configured for this runtime."
    )


if __name__ == "__main__":
    mcp.run()
