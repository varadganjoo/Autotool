"""AutoTool: a self-extending tool layer for any AI agent, served over MCP."""

__version__ = "0.1.0"
__all__ = ["anthropic_tools", "connect", "openai_tools", "run_agent"]


def __getattr__(name: str):
    # Lazy, so tool processes that import autotool.guard don't load the MCP client stack.
    if name in __all__:
        from autotool import agent

        return getattr(agent, name)
    raise AttributeError(f"module 'autotool' has no attribute {name!r}")
