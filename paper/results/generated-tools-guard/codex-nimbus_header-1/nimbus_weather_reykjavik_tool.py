import os
import httpx
from mcp.server.fastmcp import FastMCP

REQUIRED_ENV = ["NIMBUS_API_KEY"]

mcp = FastMCP("nimbus_weather_reykjavik_tool")
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:53933/nimbus/v1")


@mcp.tool()
def get_reykjavik_temperature() -> str:
    """Fetch Reykjavik current weather conditions from Nimbus and return the temperature field."""
    headers = {"X-Nimbus-Key": os.environ["NIMBUS_API_KEY"]}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/current", params={"city": "Reykjavik"}, headers=headers)
        response.raise_for_status()
        data = response.json()
    for key in ("temperature", "temp", "temperature_c", "temp_c", "current_temperature"):
        if key in data:
            return str(data[key])
    return response.text


if __name__ == "__main__":
    mcp.run()
