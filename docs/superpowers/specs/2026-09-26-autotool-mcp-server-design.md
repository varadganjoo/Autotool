# AutoTool as a self-hosted MCP server

Date: 2026-09-26 · Status: approved in chat ("this looks right … just implement it")

## Goal

Anyone can install AutoTool, add environment variables, and connect it to the agent they use:
Claude Code, Claude Desktop, Cursor, OpenClaw, or an agent they are building. The agent gets a
tool layer that grows: new tools are written, verified, sandboxed, given only their declared
credentials and mounted without restarting anything. User-hosted only; no AutoTool service.

## Decisions

- Distribution: PyPI package `autotool-mcp` (`autotool` is taken on PyPI and npm); console
  scripts `autotool` and `autotool-mcp`. `uvx autotool-mcp setup` or `pipx install autotool-mcp`.
- Transport: stdio MCP server (`autotool serve`). Every target host supports stdio.
- Who writes tool code: the connected agent, through `create_tool` (no sampling: Claude Code and
  Claude Desktop do not support it). Optional model key enables `synthesize_tool`, where
  AutoTool writes and repairs the code itself (existing generator/repair loop).
- Data: `~/.autotool/` (override `AUTOTOOL_HOME`): `tools/` (cache shared by every host),
  `.staging/`, `.env`, `keys.json` (names of keychain-stored keys, never values).

## MCP surface

| Tool | When | Behaviour |
|---|---|---|
| `create_tool(name, code, test_tool?, test_arguments?)` | always | Lint, verify in a subprocess, promote to the cache, mount, send `notifications/tools/list_changed`. Returns the mounted tools' schemas, or the redacted verification failure with `isError`. The description carries the tool contract and the available credential names. Re-creating an existing name replaces it. |
| `synthesize_tool(tool_name, capability_description)` | model key present | Existing generate → verify → repair loop, then mount + notify. |
| `run_tool(name, arguments)` | always | Calls any mounted tool by qualified name, for hosts that do not refresh their tool list. |
| `<server>__<tool>` | per mounted tool | Native tools, redacted schemas. |

## Credentials

One `ToolEnv` built from, highest precedence first:
1. Host-config environment: `AUTOTOOL_KEY_<NAME>=value` → offered as `<NAME>`.
2. OS keychain (`keyring`, service `autotool-mcp`), names indexed in `keys.json`.
3. `~/.autotool/.env`.
4. `--env-file PATH` (explicit only; the host's project `.env` is never read implicitly).

Rebuilt on every `create_tool` / `synthesize_tool` and at startup, so new keys work without a
restart. Every source name (and every `AUTOTOOL_KEY_*` variable) is stripped from tool processes
unless declared. `OPENAI_*`/`ANTHROPIC_*` in `~/.autotool/.env` configure the optional model and
are loaded into the server's own environment, never offered to tools. The existing contract is
unchanged: names only to the model, `REQUIRED_ENV` injection, encoding-aware redaction.

## CLI

- `autotool serve [--env-file PATH]`: the MCP server hosts launch.
- `autotool setup [--hosts ...] [--dry-run] [--launcher auto|uvx|path]`: register with Claude Code
  (`claude mcp add --scope user`), OpenClaw (`openclaw mcp add` when the installed version has it),
  Claude Desktop and Cursor (JSON config edit with a `.bak` backup).
- `autotool keys add NAME` (hidden prompt or `--stdin`), `keys list`, `keys remove NAME`.
- `autotool tools list` (tools + declared credentials), `tools remove NAME`.
- `autotool run "objective"`: the existing built-in agent, kept as a demo.

## Out of scope (v2)

URL-mode elicitation for missing keys, consent prompts, per-key host allowlists, tool sharing.

## Testing

Unit: credential sources and precedence, setup config writers (temp dirs), keys CLI (fake
keychain). End to end: real MCP client ↔ `autotool serve` subprocess: create_tool, list_changed,
native call, run_tool, authenticated tool against a local Bearer API with no leak, failure →
redacted error. Real host: Claude Code `claude -p --mcp-config` against the mock auth API.
