import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nimbus_weather_tool")

REQUIRED_ENV = ["NIMBUS_API_KEY"]
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:50541")


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Get current weather for a city from the Nimbus Weather API.

    Args:
        city: Name of the city to look up.
    """
    api_key = os.environ["NIMBUS_API_KEY"]
    url = f"{API_BASE.rstrip('/')}/nimbus/v1/current"
    with httpx.Client(timeout=10) as client:
        response = client.get(
            url,
            params={"city": city},
            headers={"X-Nimbus-Key": api_key},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
