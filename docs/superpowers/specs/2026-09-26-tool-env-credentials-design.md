# Authenticated tool synthesis via `.env` discovery

Date: 2026-09-26 · Status: approved design, pending implementation

## Goal

Let AutoTool synthesize tools for APIs that need credentials or other configuration, with zero
per-service setup: the user adds a variable to `.env` (e.g. `TAVILY_API_KEY=...`) and the agent
discovers it, decides which service it unlocks, writes a tool that uses it, and runs that tool with
the value injected. The LLM never sees secret values.

Success criteria

1. An objective that never names the service ("search the web for X") is solved with a synthesized
   tool that authenticates using a key discovered from `.env`.
2. No secret value appears in any message sent to the LLM (measured, not assumed).
3. A tool receives only the variables it declares.
4. Offline test suite passes; live results are reported in `paper/`.

## Non-goals

- Per-secret network egress control (host allowlists). Documented as future work.
- Defending against deliberately malicious generated code. Process isolation only, as today.
- OAuth flows / token refresh. Static credentials only.

## Design

### Discovery (`autotool/core/toolenv.py`, new)

`ToolEnv.from_dotenv(path=None)` reads the file with `dotenv_values` (default path:
`find_dotenv(usecwd=True)`). It keeps non-empty values and drops names reserved for the runtime:
prefixes `OPENAI_`, `ANTHROPIC_`, `AUTOTOOL_`. The process environment is not a discovery source.

API:

- `names -> list[str]`: sorted grantable names (shown to the LLM).
- `grant(required) -> dict[str, str]`: values for the declared names; `KeyError` naming the missing
  variable(s) if any are not available.
- `redact(text) -> str`: replaces each secret value, and its `urllib.parse.quote(v, safe="")` form,
  with `[REDACTED:<NAME>]`. A value is secret if its name matches
  `KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PRIVATE` or the value is >= 16 chars with no
  whitespace. Longest values are replaced first.
- `required_env(code) -> list[str]` (module function): reads a module-level
  `REQUIRED_ENV = [...]` / tuple of string literals via `ast`. Missing -> `[]`. Non-literal ->
  `ValueError`.

`ToolEnv()` with no values is the default everywhere, so existing behaviour is unchanged when
`.env` has no extra variables.

### Tool contract (generator prompt + verifier)

- Generated code declares `REQUIRED_ENV = ["NAME", ...]` listing every variable from the available
  list it reads, and reads them with `os.environ["NAME"]`.
- Prefer sending keys in headers over query strings; never return, log or embed keys in error text.
- The generator prompt lists the available names (not values). If there are none, the old
  "keyless public APIs only" rule applies.
- `static_check(code, available)` additionally fails when `REQUIRED_ENV` is not a literal list of
  strings or names a variable not in `available` (error lists what is available). This feeds the
  existing repair loop.

### Injection (least privilege)

`sandbox_env(extra, drop)` gains a `drop` set: all `ToolEnv` names are removed from the inherited
parent environment (in addition to the existing secret-pattern scrub), then `extra` is applied.
`extra = env_overrides | tool_env.grant(required_env(code))`.

- Verifier: computes the env per candidate before launching.
- Registry `mount`: reads the script, computes the env. A cached tool whose variable was removed
  from `.env` fails to mount with a clear error (startup logs and skips it, as today).

### Redaction points

Everything LLM-bound that can carry tool-originated text passes through `tool_env.redact`:

- `ToolRegistry.call` result content.
- `VerificationReport.error`, `.stderr`, `.smoke_output` (these feed the repair prompt and events).

### Agent awareness

`Orchestrator` appends to the system prompt, when names exist:
"Credentials/config available to tools you synthesize (values are injected at runtime, never shown
to you): A, B. If one fits the task, use it and name it in capability_description."

### CLI

`main.py`: `--env-file PATH` (default: discovered `.env`). `run_objective(..., tool_env=None)`
threads a `ToolEnv` into verifier, registry, generator and orchestrator. `.env` keeps being loaded
into `os.environ` by `llm.py` for the provider keys; this does not leak to tools because of `drop`.

## Testing

Offline (`tests/test_toolenv.py`, pytest):

- discovery drops reserved prefixes and empty values
- `redact` handles raw + URL-encoded values, longest-first, name- and shape-based secrecy
- `required_env` literal parsing; non-literal rejected
- static check rejects unavailable names
- verifier: tool sees declared var, not undeclared `.env` vars; key echoed in an error is redacted
  in the report
- orchestrator end to end (scripted provider) against a local Bearer-auth fixture API

Live (`scripts/auth_benchmark.py`, results to `results/`):

- Local mock API with four auth schemes (custom header, Bearer, query param, HTTP Basic), random
  credentials per run; objectives document the API but the key lives only in the tool env.
- Real Tavily and Composio objectives that do not name the service.
- Negative control: a service with no key available -> agent must report the gap, not fabricate.
- Ablation: tool env disabled (previous behaviour).
- Metrics: success, synthesis attempts, wall time, tokens, leaks (every LLM request is recorded and
  scanned for every secret value, raw and URL-encoded).

## Paper

Markdown in `paper/` in this repo: problem, design, threat model, evaluation (numbers from the live
run), limitations (egress control, prompt injection, redaction is best effort), future work.
