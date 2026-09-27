import json
import os
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("parcelly_tracking_tool")
PARCELLY_API_BASE = os.environ.get(
    "PARCELLY_API_BASE", "http://127.0.0.1:50541/parcelly/api"
)


@mcp.tool()
def track_parcel(
    tracking_number: str,
    username: str,
    password: str,
    base_url: str = PARCELLY_API_BASE,
) -> str:
    """Fetch Parcelly tracking information using HTTP Basic Auth.

    Args:
        tracking_number: Parcelly tracking number to look up.
        username: Username for HTTP Basic Authentication.
        password: Password for HTTP Basic Authentication.
        base_url: Parcelly API base URL; the tracking endpoint is appended to it.
    """
    url = f"{base_url.rstrip('/')}/track/{quote(tracking_number, safe='')}"
    with httpx.Client(timeout=10.0) as client:
        response = client.get(url, auth=(username, password))
    return json.dumps(
        {"status_code": response.status_code, "body": response.text},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run()
