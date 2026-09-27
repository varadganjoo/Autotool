from mcp.server.fastmcp import FastMCP

mcp = FastMCP("noop_tool")

@mcp.tool()
def noop() -> str:
    """Return a no-op string."""
    return "ok"

if __name__ == "__main__":
    mcp.run()
