# Weekly AutoTool improvements

## Discovery / aha — 2026-11-11

We expected `refresh_tools` to recover a cached capability after its worker crashed.
Dogfooding the published 0.1.2 in a fresh Windows/Python 3.11 virtual environment showed
that it returned “No new cached tools available” and the capability stayed unusable.
The registry retains the dead connection after a call raises. Reconciliation checks source
and credentials, while refresh skips every registered worker. A remembered schema can
outlive the process that could execute it.

**Ideas considered.** Search cached capabilities without starting processes, evict idle
workers, or repair the existing failure path. This week's new evidence selected recovery.
Search and eviction still need metadata and lifecycle decisions beyond this small fix.

**Implementation and acceptance.** When a call raises, unload its worker under the
existing per-server lock, provided it is still that same connection. Return the failure
once with a reminder to inspect side effects before retrying. `refresh_tools` can then
reload the cached source through the existing credential policy. A late failure from a
replaced connection must leave the replacement running. A tool-reported application
error must leave its working process registered. Timeouts must preserve cached source
and allow an explicit reload. No dependencies, permissions or storage formats were added.

**Before and after.** Both real stdio crash-recovery tests failed on the original code
because refresh skipped the dead worker. Both passed after the fix. Separate real-process
checks cover application errors, a late call failure during replacement, and timeout
recovery. The concurrency check also asserts the failing invocation is executed once.
Run `python -m pytest -q tests/test_server.py -k recovers_a_worker` and
`python -m pytest -q tests/test_synthesis.py -k "keeps_a_worker or late_call_failure or call_timeout_unloads"`.
An isolated installation of the candidate wheel recovered the same crashed capability
through the public client API and returned `alive`. The published 0.1.2 baseline failed
that same probe. These compare behavior, not performance.

**Verification.** The full offline suite passed with 168 tests and one skip, then the
additional timeout regression passed separately. Ruff lint and formatting, wheel and
source builds, strict Twine checks, both isolated installations' `pip check`, the current
`pip-audit` scan and the tracked-file secret scan passed. The secret baseline update
only moves a reviewed README placeholder's line number. No static type gate is configured.

**Delivery.** [Implementation commit 9892330](https://github.com/varadganjoo/Autotool/commit/989233007298d0c01558a180457f17e3f8e90b16)
is proposed in [PR #3](https://github.com/varadganjoo/Autotool/pull/3). Its checks record
cross-platform results for the submitted revision.

The previously requested [0.1.2 release](https://pypi.org/project/autotool-mcp/0.1.2/)
also completed its existing protected publishing workflow. A fresh PyPI installation
verified tool creation in one client and refresh plus a successful call returning `42`
in a second client that was already connected. The recovery fix above is proposed work
for a subsequent release.

**Limits.** Recovery follows an observed call exception. A process that dies while idle
can still appear in listings until a call discovers its failed connection. Explicit reload
starts a fresh process and loses its transient state. The original call may have completed
external side effects before failing, so the caller must decide whether to invoke it again.
Live Claude/ChatGPT apps, hostile-code OS isolation and memory benchmarks are outside this
fix. No speed or memory improvement is claimed.

**Next question.** Can discovery distinguish saved, running and healthy capabilities
without executing arbitrary tool code or adding a process per catalog entry?

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

**Delivery and checks.** Ruff lint and formatting, strict Twine checks on the wheel and
source archive, `pip check` on the isolated wheel, the tracked-file secret scan, and
`pip-audit` passed locally. The [implementation commit](https://github.com/varadganjoo/Autotool/commit/144ddf803243af80a024c8d8e298e8b33d137d65)
and [pull request checks](https://github.com/varadganjoo/Autotool/pull/2/checks) record the
delivered change and cross-platform verification.

**Limits.** Each explicit refresh tries the existing shared cache and can start Python
processes. Failed entries are logged and retried on a later explicit refresh. The cache
is a local trust boundary. No live Claude or ChatGPT integration was exercised here.

**Next question.** Can a running agent discover the one relevant cached tool before
starting any tool processes? Measure what the agent needs to select it reliably before
choosing a metadata format or search strategy.
