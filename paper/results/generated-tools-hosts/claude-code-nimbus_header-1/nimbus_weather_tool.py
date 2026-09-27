import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["NIMBUS_API_KEY"]

NIMBUS_API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:57311/nimbus/v1")

mcp = FastMCP("nimbus_weather_tool")


@mcp.tool()
def current(city: str) -> str:
    """Get current weather conditions for a city from the Nimbus Weather API.

    Args:
        city: The name of the city to look up, e.g. "Reykjavik".
    """
    api_key = os.environ["NIMBUS_API_KEY"]
    headers = {"X-Nimbus-Key": api_key}
    with httpx.Client(timeout=10.0) as client:
        response = client.get(
            f"{NIMBUS_API_BASE}/current",
            params={"city": city},
            headers=headers,
        )
        response.raise_for_status()
        return json.dumps(response.json())


if __name__ == "__main__":
    mcp.run()
