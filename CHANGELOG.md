# Changelog

## 0.1.0 — first public release

- `autotool serve`: a user-hosted MCP server that any agent connects to. The agent writes tools
  with `create_tool`; AutoTool verifies each one in a subprocess, mounts it live
  (`tools/list_changed`, plus `run_tool` for hosts that don't refresh) and keeps it in
  `~/.autotool/tools` for every host on the machine.
- `synthesize_tool` when a model key is set in `~/.autotool/.env` (install `autotool-mcp[models]`).
- Credentials by name only: from the host's MCP config (`AUTOTOOL_KEY_*`), the OS keychain
  (`autotool keys add`) or `~/.autotool/.env`. Each tool gets only what it declares in
  `REQUIRED_ENV`, and values a tool echoes back (raw, URL-encoded, JSON-escaped) are redacted
  before reaching the model.
- Consent prompts before a tool first gets credentials, asked again only when the risk changes;
  `--dangerously-allow-all-tools` to skip them.
- Per-key host allowlists (`autotool keys allow`) and an in-process guard, on by default
  (`--sandbox off` when AutoTool already runs in a sandbox).
- `autotool setup` for Claude Code, Codex, Claude Desktop, Cursor and OpenClaw.
