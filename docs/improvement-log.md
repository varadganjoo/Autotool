# Weekly AutoTool improvements

## Discovery / aha — 2026-11-04

We expected two running MCP hosts sharing an AutoTool home to see a tool once either one
created it. With the published 0.1.1 wheel, one host verified and saved `math_tool.py`.
The other host listed its tools again and still got `Unknown tool 'math_tool__add'` from
`run_tool`. Startup enumerates the cache, while request-time reconciliation only checks
scripts the session already mounted. Disk persistence and live discovery are separate.

**Ideas considered.** Rescan on every listing, watch the shared directory for changes,
or give agents an explicit `refresh_tools` call. We chose the explicit call so ordinary
listings need no extra process starts, even when the cache has broken entries.

**Implementation and acceptance.** An already-connected agent can ask AutoTool to mount
cached scripts that this session hasn't loaded. The call returns their tool names for
`run_tool` and signals both MCP notification modes. Repeating it leaves unchanged tools
running. The startup credential policy applies, so a missing grant or broken script
doesn't block other entries. Granting approval allows a later retry, and revocation still
removes the tool on the next request. No new dependencies or persistent state are needed.

**Before and after.** On Windows with Python 3.11, the three cases selected by
`python -m pytest -q tests/test_server.py -k refresh_tools` failed on the original code and
passed after implementation. The tests use real stdio subprocesses and an isolated home.
They cover live handoff in both protocol modes, repeat refresh, and recovery past a broken
entry without bypassing approval. The handoff test invokes the reused tool and gets `42`.
In a separate core-only virtual environment, the rebuilt wheel also returned `42` from a
native tool call on the original reader connection after refresh.

**Limits.** Each explicit refresh tries the existing shared cache and can start Python
processes. Failed entries are logged and retried on a later explicit refresh. The cache
is a local trust boundary. No live Claude or ChatGPT integration was exercised here.

**Next question.** Can a running agent discover the one relevant cached tool before
starting any tool processes? Measure what the agent needs to select it reliably before
choosing a metadata format or search strategy.
