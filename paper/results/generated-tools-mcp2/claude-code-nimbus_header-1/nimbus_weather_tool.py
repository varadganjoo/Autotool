import os
import json
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["NIMBUS_API_KEY"]

NIMBUS_API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53984/nimbus/v1")

mcp = MCPServer("nimbus_weather_tool")


@mcp.tool()
def current(city: str) -> str:
    """Get the current weather conditions for a city from the Nimbus Weather API.

    Args:
        city: The name of the city to look up current conditions for.
    """
    api_key = os.environ["NIMBUS_API_KEY"]
    url = f"{NIMBUS_API_BASE}/current"
    try:
        resp = httpx2.get(
            url,
            params={"city": city},
            headers={"X-Nimbus-Key": api_key},
            timeout=10.0,
        )
    except httpx2.HTTPError as exc:
        raise ToolError(f"Nimbus API request failed: {exc}") from exc

    if resp.status_code != 200:
        raise ToolError(
            f"Nimbus API returned status {resp.status_code} for city '{city}'"
        )

    return json.dumps(resp.json())


if __name__ == "__main__":
    mcp.run()
