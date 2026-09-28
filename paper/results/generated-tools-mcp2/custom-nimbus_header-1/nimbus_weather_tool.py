import os
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["NIMBUS_API_KEY"]
mcp = MCPServer("nimbus_weather_tool")
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53984/nimbus/v1")


@mcp.tool()
def current_weather(city: str) -> str:
    """Get current weather conditions for a city from Nimbus.

    Args:
        city: City name to look up, such as Reykjavik.
    """
    key = os.environ["NIMBUS_API_KEY"]
    with httpx2.Client(timeout=10) as client:
        response = client.get(
            f"{API_BASE}/current",
            params={"city": city},
            headers={"X-Nimbus-Key": key},
        )
    if response.status_code != 200:
        raise ToolError(f"Nimbus Weather API returned HTTP {response.status_code} for current conditions in {city}")
    return response.text


if __name__ == "__main__":
    mcp.run()
