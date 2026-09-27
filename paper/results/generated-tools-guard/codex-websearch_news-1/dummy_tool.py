import json
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("dummy_tool")
@mcp.tool()
def noop() -> str:
    """Return an empty JSON array."""
    return json.dumps([])
if __name__ == "__main__":
    mcp.run()
