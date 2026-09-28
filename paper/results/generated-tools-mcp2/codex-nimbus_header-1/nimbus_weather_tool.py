import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["NIMBUS_API_KEY"]

mcp = MCPServer("nimbus_weather_tool")
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53984/nimbus/v1")


@mcp.tool()
def get_current_weather(city: str) -> str:
    """Fetch current weather conditions from Nimbus for a city.

    Args:
        city: City name to query, such as Reykjavik.
    """
    headers = {"X-Nimbus-Key": os.environ["NIMBUS_API_KEY"]}
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/current", params={"city": city}, headers=headers)
    if resp.status_code != 200:
        raise ToolError(f"Nimbus API returned HTTP {resp.status_code} for city {city}")
    return resp.text


if __name__ == "__main__":
    mcp.run()
