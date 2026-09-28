import os
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["COMPOSIO_API_KEY"]
API_BASE = os.environ.get("COMPOSIO_API_BASE", "https://backend.composio.dev/api/v3")
mcp = MCPServer("composio_github_count_tool")

@mcp.tool()
def github_tool_count() -> str:
    """Get the number of tools in Composio's GitHub toolkit.

    No parameters are required. Fetches the GitHub toolkit's tools from Composio and counts them.
    """
    key = os.environ["COMPOSIO_API_KEY"]
    headers = {"x-api-key": key, "accept": "application/json"}
    with httpx2.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/tools", headers=headers, params={"toolkit_slug": "github", "limit": 1000})
    if resp.status_code != 200:
        raise ToolError(f"Composio API returned HTTP {resp.status_code} while fetching GitHub tools")
    data = resp.json()
    if isinstance(data, list):
        tools = data
    elif isinstance(data, dict):
        tools = data.get("items", data.get("tools", data.get("data")))
        if isinstance(tools, dict):
            tools = tools.get("items", tools.get("tools", []))
        if not isinstance(tools, list):
            raise ToolError("Composio API response did not contain a recognizable GitHub tools list")
    else:
        raise ToolError("Composio API returned an unrecognized GitHub tools response")
    return str(len(tools))

if __name__ == "__main__":
    mcp.run()
