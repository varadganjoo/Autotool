import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nimbus_weather_tool")
API_BASE = os.environ.get(
    "NIMBUS_API_BASE", "http://127.0.0.1:50541/nimbus/v1"
).rstrip("/")


@mcp.tool()
def get_current_weather(city: str, api_key: str) -> str:
    """Request current weather for a city from the Nimbus Weather API.

    Args:
        city: City name to look up; sent as the URL-encoded city query parameter.
        api_key: Nimbus API key, sent in the X-Nimbus-Key request header. An empty
            value is sent as supplied; this tool does not invent or substitute a key.

    Returns the HTTP status and the parsed JSON response, or response text when
    the response is not valid JSON. Non-success HTTP statuses are returned too.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/current",
            params={"city": city},
            headers={"X-Nimbus-Key": api_key},
        )

    try:
        body = response.json()
    except ValueError:
        body = response.text

    return json.dumps({"status": response.status_code, "body": body})


if __name__ == "__main__":
    mcp.run()
