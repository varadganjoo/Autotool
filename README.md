# AutoTool

**A tool layer that grows, for any AI agent.** Connect AutoTool to Claude Code, Codex, Cursor,
Claude Desktop, OpenClaw or an agent you are building. When your agent needs something it has no tool for,
such as a web API, live data or your company's internal service, it writes the tool. AutoTool then:

- **verifies** it: lint, launch in a subprocess, smoke test;
- **guards** it: the tool runs in its own process with only the credentials it declares;
- **mounts** it, live, with no restart;
- **keeps** it for every agent on your machine.

The model is told your keys' **names** (`TAVILY_API_KEY`), never their values, and values that a tool
echoes back are redacted before the model sees them.

```
your agent (Claude Code, Codex, Cursor, your own) ──MCP──▶ autotool serve
                                                               ├─ create_tool   the agent writes a tool
                                                               ├─ run_tool      call any created tool
                                                               ├─ weather_tool__current  ─▶ own process, gets WEATHER_API_KEY only
                                                               └─ tavily_tool__search    ─▶ own process, gets TAVILY_API_KEY only
```

## Quick start

Python 3.11+. Pick the way you work:

### Build your own agent (Python)

```bash
pip install "autotool-mcp[models]"
export OPENAI_API_KEY=sk-...        # your agent's model (or ANTHROPIC_API_KEY)
```

```python
import asyncio, autotool
from autotool.core.llm import default_provider

answer = asyncio.run(
    autotool.run_agent(
        "What are the top 3 stories on Hacker News right now?",
        default_provider(),
        on_consent=lambda question: input(question + " [y/N] ") == "y",  # asked before a tool gets a key
    )
)
print(answer)
```

The agent has no Hacker News tool. It writes one, AutoTool verifies and mounts it, and the agent
uses it. Run it again and the tool is already there.

**Local or other models.** Any OpenAI-compatible endpoint works: Ollama, LM Studio, vLLM,
OpenRouter, and others. Set a base URL and a model name; local servers need no key.

```bash
export OPENAI_BASE_URL=http://localhost:11434/v1   # Ollama; LM Studio: http://localhost:1234/v1
export OPENAI_LLM=qwen2.5:14b                      # the model name on that server
```

`default_provider()` then talks to that endpoint through the Chat Completions API. Pick a model
with tool calling. Writing a working tool is real coding, so small models fail more often than
frontier ones. `AUTOTOOL_PROVIDER=openai` keeps OpenAI's Responses API even with a custom base URL.

**Already have an agent loop?** Connect it to AutoTool and pass tool calls through:

```python
async with autotool.connect() as client:  # starts AutoTool as an MCP server
    listed = await client.list_tools()  # create_tool, run_tool, every tool created so far
    tools = autotool.openai_tools(listed)  # or autotool.anthropic_tools(listed)
    result = await client.call_tool(name, arguments)  # whatever your model asked for
```

Frameworks with stdio MCP support (OpenAI Agents SDK `MCPServerStdio`, LangGraph via
`langchain-mcp-adapters`) can also launch `autotool serve` directly.

### Add it to Claude Code, Codex, Cursor, Claude Desktop or OpenClaw

```bash
pip install autotool-mcp            # or: pipx install autotool-mcp / uv tool install autotool-mcp
autotool setup                      # registers AutoTool with every agent app it finds
autotool keys add TAVILY_API_KEY    # stored in your OS keychain; add as many as you like
```

Restart your agent app and ask for something it can't do yet: *"Search the web for this week's
James Webb news"*. It writes a Tavily tool. AutoTool asks whether that tool may use
`TAVILY_API_KEY`, verifies it, hands it that key and nothing else, and the answer comes back.
Next time, the tool is already there.

`autotool setup --dry-run` shows what it would change first. JSON configs (Claude Desktop, Cursor)
are backed up to `.bak` before editing. Existing entries keep their `env` block, and an existing
Claude Code or Codex entry is left untouched.

## Adding credentials

You add environment variables. AutoTool offers their **names** to your agent, and a created tool
gets a value only if it declares that name in its code (`REQUIRED_ENV = ["TAVILY_API_KEY"]`).
Pick any of these places (the first match wins):

| Where | How |
|---|---|
| Your host's MCP config | `"env": {"AUTOTOOL_KEY_TAVILY_API_KEY": "tvly-..."}`. The prefix makes sharing opt-in. |
| OS keychain | `autotool keys add TAVILY_API_KEY` (hidden prompt; `--stdin` for scripts) |
| `~/.autotool/.env` | `TAVILY_API_KEY=tvly-...`, one per line |
| Any file | `autotool serve --env-file path/to/.env` |

A new key can be used by the next tool your agent creates, with no restart. Your agent's tool list
shows the new name after its next refresh, and a cached tool that was skipped for a missing key
loads on the next restart. `autotool keys list` shows names. `autotool tools list` shows
which tools hold which credentials. If a tool needs a key you don't have, your agent is told
exactly what to run (`autotool keys add STRIPE_API_KEY`).

## Let AutoTool write the tools

If your agent is small or not good at writing code, give AutoTool a model of its own in
`~/.autotool/.env`: `OPENAI_API_KEY` (default model `gpt-6-sol`), `ANTHROPIC_API_KEY` (default
`claude-opus-5`), or an OpenAI-compatible endpoint (`OPENAI_BASE_URL` + `OPENAI_LLM`, e.g. a local
Ollama model). Only a key in that file counts: a key your host happens to have in its environment
is never used, so nothing gets billed by surprise. A `synthesize_tool` tool then appears: your
agent describes the capability, and AutoTool writes, verifies, repairs and mounts it.

## What a created tool looks like

```python
import os

import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REQUIRED_ENV = ["TAVILY_API_KEY"]  # the only credential this process will receive
mcp = MCPServer("tavily_tool")
API_BASE = os.environ.get("TAVILY_API_BASE", "https://api.tavily.com")


@mcp.tool()
def search(query: str, max_results: int = 5) -> str:
    """Search the web with Tavily."""
    with httpx2.Client(timeout=10) as client:
        r = client.post(
            f"{API_BASE}/search",
            json={"query": query, "max_results": max_results},
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
        )
    if r.status_code != 200:
        raise ToolError(f"Tavily returned HTTP {r.status_code}: {r.text[:200]}")
    return r.text


if __name__ == "__main__":
    mcp.run()
```

A tool is a plain [MCP](https://modelcontextprotocol.io) server built on the official Python SDK
(v2). `ToolError` messages reach the agent; an unexpected exception's traceback goes to the
verifier, which feeds it back so the tool can be fixed.

## Security

**Consent.** The first time a tool asks for credentials, AutoTool asks *you*, through your agent
app's approval prompt: "Allow `tavily_tool` to use TAVILY_API_KEY? It can only send them to
api.tavily.com." Nothing runs with the key until you say yes. You are asked again only when the risk changes:
- **Key with a host allowlist** (and the guard on): rewrites of the tool don't ask again. A
  rewrite can't send the key anywhere new. It asks again only if the tool wants more keys or you
  widen the allowlist.
- **Key without an allowlist:** every new version of the tool asks, because a rewrite could send
  the key anywhere. Setting allowlists means fewer prompts.

Removing a tool revokes its approval. If your app can't show prompts, the
agent is told to ask you to run the approval yourself:

```bash
autotool tools approve tavily_tool TAVILY_API_KEY
autotool tools revoke tavily_tool
autotool serve --dangerously-allow-all-tools   # never ask (or AUTOTOOL_CONSENT=dangerously-allow-all)
```

`--dangerously-allow-all-tools` gives every tool the credentials it declares without asking.
Use it for CI, or if you'd rather not approve tools. The guard and host allowlists still apply,
and the server logs a warning at startup.

**Per-key host allowlists.** Say where a key may be sent. A tool holding that key can then only
reach those hosts (plus localhost, which never leaves your machine):

```bash
autotool keys allow TAVILY_API_KEY api.tavily.com
autotool keys allow GITHUB_TOKEN api.github.com "*.githubusercontent.com"
autotool keys allow TAVILY_API_KEY          # no hosts: remove the limit
```

**The guard (on by default, optional).** Every tool runs under a Python audit hook that the tool
cannot remove. It enforces the allowlists and blocks:
- subprocesses and shell commands;
- loading native code;
- the OS keychain and credential stores;
- reading AutoTool's credential files and your agent apps' MCP configs;
- creating, changing or deleting anything outside the temp directory.

This applies to every tool, including ones that declare no keys.

It is a guard, not a jail: native code or interpreter bugs can get past it. If AutoTool already
runs inside a sandbox (a container, a VM, a devcontainer), turn it off:
`autotool serve --sandbox off` (or `AUTOTOOL_SANDBOX=off` in your host's MCP config). Only an
explicit `off`, `0`, `false` or `no` turns it off; anything else keeps it on. Host
allowlists are then not enforced; consent still is.

**Always on:**
- The model is only ever *told* credential **names**. Values a tool echoes back (raw, URL-encoded
  or JSON-escaped) are redacted. A tool written to disguise a key (e.g. base64) could still reveal
  it; that is what consent and host allowlists are for.
- Each tool process gets only the variables in its `REQUIRED_ENV`, plus an allowlist of OS
  basics: PATH, temp dirs, locale, proxy and CA settings, and `*_API_BASE` overrides. Nothing else
  from your host's environment reaches it (no `AWS_*`, no `DATABASE_URL`).
- Before anything a tool produces reaches the model (output, errors, tracebacks, schemas), secret
  values are replaced with `[REDACTED:NAME]`. This covers raw, URL-encoded and JSON-escaped forms.

For a hard boundary, run AutoTool in a container with the guard off.

The design and its evaluation are written up in [the paper](https://github.com/varadganjoo/Autotool/blob/main/paper/autotool.md).

## Hosts

| Host | Connect | Notes |
|---|---|---|
| Claude Code | `autotool setup` (runs `claude mcp add --scope user`) | Headless `claude -p`: set `MCP_CONNECTION_NONBLOCKING=0` so the first turn waits for AutoTool. |
| Codex | `autotool setup` (runs `codex mcp add`) | Headless `codex exec` auto-rejects MCP calls: add `-c mcp_servers.autotool.default_tools_approval_mode="approve"`. |
| Claude Desktop, Cursor | `autotool setup` (edits their `mcpServers` config) | Restart the app. |
| OpenClaw | `autotool setup` (`openclaw mcp set` on releases that have it) | Older releases: setup prints the config snippet to paste. |
| Anything else | point it at `autotool serve` (stdio) | |

AutoTool speaks both MCP protocol eras: hosts on the 2026-07-28 revision get consent through an
input-required round trip and hear about new tools on `subscriptions/listen`; older hosts get a
form elicitation and `notifications/tools/list_changed`.

## Development

```bash
python -m venv venv && venv/bin/pip install -e ".[dev]"   # Windows: venv\Scripts\pip
pytest                                                     # offline suite
ruff check . && ruff format --check .                      # lint
autotool run "What is the top story on Hacker News?"       # demo agent: needs [models] + a key in ./.env;
                                                           # no consent prompts or allowlists, uses ./tools
python scripts/auth_benchmark.py --trials 3                # credentials benchmark
python scripts/host_benchmark.py --trials 3                # Claude Code + custom-agent benchmark
```

Built on the MCP Python SDK 2.x, `httpx2`, the OpenAI SDK 3.x (Responses API) and the Anthropic
SDK 1.x.
