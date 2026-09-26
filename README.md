# AutoTool

A self-synthesizing MCP agent runtime. AutoTool starts with **zero** domain tools. When an objective
needs a capability it lacks, the agent calls its `synthesize_tool` meta-tool, and AutoTool:

1. **Generates** a standalone `FastMCP` server script with Claude (`autotool/synthesis/generator.py`)
2. **Verifies** it: static lint, then launched as an ephemeral subprocess, driven over MCP stdio with
   `list_tools()` + a smoke-test `call_tool()` under a 15 s timeout (`verifier.py`)
3. **Repairs** it on failure by feeding the code + traceback/stderr back to the LLM, up to 3 retries (`repair.py`)
4. **Hot-loads** the verified server into the live session with no restart (`core/registry.py`,
   `clients/dynamic_client.py`). The new tools are in the LLM's tool list on the very next turn.
5. **Caches** it in `./tools/<name>.py`, so later runs mount it at startup.

```
autotool/core/orchestrator.py   agent loop + synthesize_tool meta-tool
autotool/core/registry.py       live MCP sessions, namespaced routing (<server>__<tool>)
autotool/core/llm.py            AnthropicProvider (Claude) + ScriptedProvider (offline/tests)
autotool/core/schema.py         pydantic models
autotool/clients/dynamic_client.py  stdio ClientSession wrapper, OpenAI/Anthropic schema export
autotool/synthesis/             generator / verifier / repair
```

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...          # model defaults to claude-opus-5; override with AUTOTOOL_MODEL or --model
python -m autotool.main "Fetch the current top 3 stories from Hacker News using their public API and return the titles and URLs."
```

## Demo

```bash
python scripts/demo_hackernews.py --mode live      # Claude writes the tool, real HN API
python scripts/demo_hackernews.py --mode offline   # no key/network: scripted LLM + local HN fixture
```

The offline mode replays a fixed LLM script. Its first draft is deliberately broken, so the repair
loop runs. The tool talks to a local HN-compatible fixture server through `HN_API_BASE`. Everything
else is the real runtime: staging, subprocess verification, MCP stdio, hot-loading and orchestration.

## Notes

- Generated tools run with a scrubbed environment: variables matching `*API_KEY*`, `*TOKEN*` and
  `*SECRET*` are removed. A static lint also rejects `subprocess`, `eval`/`exec` and stdout `print`.
  This is process isolation, **not** a security sandbox. Run AutoTool in a container if that matters.
- Requests use server-side refusal fallbacks (`fallbacks="default"`); disable them with `--no-fallbacks`.
- `mcp` is pinned `<2` because `mcp.server.fastmcp.FastMCP` is the 1.x API.
- Tests: `pytest` (offline, ~15 s).
