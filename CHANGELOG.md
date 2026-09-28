# Changelog

## 0.1.0 — first public release

- Python API: `autotool.run_agent(prompt, provider)` is a complete agent that writes the tools it
  needs; `autotool.connect()` gives your own agent loop an AutoTool session, with
  `autotool.openai_tools()` / `autotool.anthropic_tools()` for tool schemas.
- `autotool serve`: a user-hosted MCP server that any agent connects to. The agent writes tools
  with `create_tool`; AutoTool verifies each one in a subprocess, mounts it live
  (`tools/list_changed`, plus `run_tool` for hosts that don't refresh) and keeps it in
  `~/.autotool/tools` for every host on the machine.
- `synthesize_tool` when a model is configured in `~/.autotool/.env` (install `autotool-mcp[models]`).
- OpenAI-compatible endpoints (Ollama, LM Studio, vLLM, OpenRouter): set `OPENAI_BASE_URL` and
  `OPENAI_LLM`; AutoTool uses Chat Completions there, with a JSON fallback for structured output.
- Credentials by name only: from the host's MCP config (`AUTOTOOL_KEY_*`), the OS keychain
  (`autotool keys add`) or `~/.autotool/.env`. Each tool gets only what it declares in
  `REQUIRED_ENV`, and values a tool echoes back (raw, URL-encoded, JSON-escaped) are redacted
  before reaching the model.
- Consent prompts before a tool first gets credentials, asked again only when the risk changes;
  `--dangerously-allow-all-tools` to skip them.
- Per-key host allowlists (`autotool keys allow`) and an in-process guard, on by default
  (`--sandbox off` when AutoTool already runs in a sandbox).
- `autotool setup` for Claude Code, Codex, Claude Desktop, Cursor and OpenClaw.
- Built on the MCP Python SDK 2.x and speaks both protocol eras: 2026-07-28 hosts get consent
  through an input-required round trip and tool-list changes on `subscriptions/listen`; older
  hosts get form elicitation and `notifications/tools/list_changed`.
- Current stack throughout: `httpx2`, the OpenAI SDK 3.x (Responses API; default `gpt-6-sol`), the
  Anthropic SDK 1.x (default `claude-opus-5`, server-side refusal fallbacks), Python 3.11-3.14.
