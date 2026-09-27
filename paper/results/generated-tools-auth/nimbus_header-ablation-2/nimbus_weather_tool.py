import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nimbus_weather_tool")

# Credentials are optional; no credential is required or hard-coded.
OPTIONAL_ENV = ["NIMBUS_API_KEY", "NIMBUS_KEY"]
API_BASE = os.environ.get(
    "NIMBUS_API_BASE", "http://127.0.0.1:50541/nimbus/v1"
).rstrip("/")


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Get current weather for a city from the Nimbus Weather API.

    Args:
        city: City name to look up. The HTTP client URL-encodes this value.

    Returns the HTTP status and the parsed response JSON without changing the
    response's temperature or units fields. If a Nimbus key is available in
    the environment, it is sent using the X-Nimbus-Key header. Non-success
    HTTP statuses are included in the result so callers can inspect the API's
    status and response body.
    """
    headers = {}
    api_key = os.environ.get("NIMBUS_API_KEY") or os.environ.get("NIMBUS_KEY")
    if api_key:
        headers["X-Nimbus-Key"] = api_key

    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{API_BASE}/current",
            params={"city": city},
            headers=headers,
        )
        return json.dumps(
            {"status": response.status_code, "data": response.json()},
            ensure_ascii=False,
        )


if __name__ == "__main__":
    mcp.run()
