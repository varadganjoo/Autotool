import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stripe_charges_tool")


@mcp.tool()
def get_recent_charges() -> str:
    """Report why recent Stripe charges cannot be retrieved in this configuration.

    Stripe's charges endpoint requires an authenticated secret key. No credentials
    are available or permitted for this server, so it cannot retrieve charges.
    """
    return json.dumps({
        "error": (
            "Cannot retrieve Stripe charges: GET /v1/charges requires an "
            "authenticated Stripe secret key, and none is available."
        )
    })


if __name__ == "__main__":
    mcp.run()
