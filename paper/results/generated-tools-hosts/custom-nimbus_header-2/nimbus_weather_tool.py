import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["NIMBUS_API_KEY"]
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:57311/nimbus/v1")
API_KEY = os.environ["NIMBUS_API_KEY"]
mcp = FastMCP("nimbus_weather_tool")


@mcp.tool()
def current_conditions(city: str) -> str:
    """Fetch Nimbus current weather conditions for a city.

    Args:
        city: City name to request, such as Reykjavik.
    """
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/current",
            params={"city": city},
            headers={"X-Nimbus-Key": API_KEY},
        )
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
