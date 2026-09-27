import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nimbus_weather_tool_result")
REQUIRED_ENV = ["NIMBUS_API_KEY"]
API_BASE = os.environ.get("NIMBUS_API_BASE", "http://127.0.0.1:61476/nimbus/v1")


@mcp.tool()
def reykjavik_temperature() -> str:
    """Fetch Reykjavik current weather from Nimbus and return the response text."""
    headers = {"X-Nimbus-Key": os.environ["NIMBUS_API_KEY"]}
    with httpx.Client(timeout=10) as client:
        response = client.get(f"{API_BASE}/current", params={"city": "Reykjavik"}, headers=headers)
        response.raise_for_status()
        return response.text


if __name__ == "__main__":
    mcp.run()
