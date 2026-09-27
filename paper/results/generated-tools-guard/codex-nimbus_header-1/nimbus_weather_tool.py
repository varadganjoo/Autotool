import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["NIMBUS_API_KEY"]

mcp = FastMCP("nimbus_weather_tool")
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53933/nimbus/v1")


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Fetch current weather conditions from Nimbus.

    Args:
        city: City name to query.
    """
    headers = {"X-Nimbus-Key": os.environ["NIMBUS_API_KEY"]}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/current", params={"city": city}, headers=headers)
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
