import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["NIMBUS_API_KEY"]
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53933/nimbus/v1")
mcp = FastMCP("nimbus_weather_tool")


@mcp.tool()
def current_weather(city: str) -> str:
    """Get current weather conditions for a city from Nimbus.

    Args:
        city: City name to look up, such as Reykjavik.
    """
    api_key = os.environ["NIMBUS_API_KEY"]
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/current",
            params={"city": city},
            headers={"X-Nimbus-Key": api_key},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
