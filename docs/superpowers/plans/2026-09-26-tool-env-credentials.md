# Authenticated Tool Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synthesized tools can call authenticated APIs using variables discovered from `.env`, with each tool receiving only the variables it declares and no secret value ever reaching the LLM.

**Architecture:** A new `ToolEnv` (autotool/core/toolenv.py) loads `.env`, exposes variable names, grants values per tool from a module-level `REQUIRED_ENV` declaration parsed with `ast`, and redacts secret values in any percent/escape encoding. The verifier, registry, generator prompt and orchestrator prompt are wired to it. A live benchmark measures success, least privilege and leaks; results feed a Markdown paper.

**Tech Stack:** Python 3.11+, `mcp` 1.x FastMCP, `python-dotenv` (already a dependency), `httpx`, pytest + pytest-asyncio (auto mode).

**Spec:** `docs/superpowers/specs/2026-09-26-tool-env-credentials-design.md`

## Global Constraints

- No new dependencies. `python-dotenv>=1.0,<2` is already in `pyproject.toml`.
- The LLM sees variable names only, never values.
- Reserved prefixes never offered to tools: `OPENAI_`, `ANTHROPIC_`, `AUTOTOOL_`.
- Only `.env` (or `--env-file`) is a discovery source, never the process environment.
- A tool process receives only the `.env` variables named in its `REQUIRED_ENV`; every other `.env` variable is removed from its inherited environment.
- Redaction marker is exactly `[REDACTED:<NAME>]`.
- Secret classification: value length >= 8 AND (name matches `KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PRIVATE`, case-insensitive, OR value >= 16 chars, no whitespace, no `://`). Refines the spec's shape rule so URLs and short flags such as `AUTH_MODE=on` never mangle output.
- Run commands on this Windows machine with `venv/Scripts/python`. Git needs `-c safe.directory=*` (the D: drive does not record ownership).

## Review Focus

1. A key containing URL-reserved characters (`+ / =`) that shows up percent-encoded inside an httpx error URL must still be redacted. Pinned in Task 3's end-to-end test, which uses such a key.
2. A cached tool whose variable was removed from `.env` must be skipped at startup with a message naming the variable, not crash the run. Pinned in Task 3.
3. `.env` files with quotes, `export` prefixes and empty values must parse. Pinned in Task 1.
4. Short or non-secret values (`AUTH_MODE=on`, URLs, city names) must not be redacted. Pinned in Task 1.
5. Annotated `REQUIRED_ENV: list[str] = [...]` must be recognised like the plain form. Pinned in Task 1.

---

### Task 1: `ToolEnv` discovery, grants, redaction; `sandbox_env(drop=...)`

**Files:**
- Create: `autotool/core/toolenv.py`
- Modify: `autotool/clients/dynamic_client.py` (`sandbox_env`)
- Test: `tests/test_toolenv.py` (new)

**Interfaces:**
- Produces:
  - `required_env(code: str) -> list[str]` (raises `ValueError` for a non-literal declaration)
  - `ToolEnv(values: dict[str, str | None] | None = None)`
  - `ToolEnv.from_dotenv(path: str | Path | None = None) -> ToolEnv`
  - `ToolEnv.names -> list[str]`
  - `ToolEnv.grant(required: Iterable[str]) -> dict[str, str]` (raises `LookupError`)
  - `ToolEnv.env_for(code: str, overrides: dict[str, str] | None = None) -> dict[str, str]`
  - `ToolEnv.redact(text: str | None) -> str | None`
  - `ToolEnv.leaked(text: str) -> list[str]`
  - `sandbox_env(extra: dict[str, str] | None = None, drop: Iterable[str] = ()) -> dict[str, str]`

- [ ] **Step 1: Write the failing tests** — create `tests/test_toolenv.py`:

```python
"""Offline tests for .env-discovered tool credentials: discovery, least-privilege
injection, redaction, and an end-to-end run against a local Bearer-auth API."""

from __future__ import annotations

from urllib.parse import quote, quote_plus

import pytest

from autotool.clients.dynamic_client import sandbox_env
from autotool.core.toolenv import ToolEnv, required_env

ALPHA = "alpha-" + "a" * 20
BETA = "beta-" + "b" * 20


def env(**extra: str) -> ToolEnv:
    return ToolEnv({"ALPHA_API_KEY": ALPHA, "BETA_API_KEY": BETA, "PLAIN_SETTING": "hello", **extra})


# ---------------------------------------------------------------- discovery / grants


def test_from_dotenv_drops_reserved_and_empty(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "OPENAI_API_KEY=sk-x\nANTHROPIC_API_KEY=a\nAUTOTOOL_MODEL=m\nEMPTY=\n\n"
        'TAVILY_API_KEY="tvly-quoted-value-123"\nexport PLAIN_SETTING=hello\n'
    )
    tool_env = ToolEnv.from_dotenv(f)
    assert tool_env.names == ["PLAIN_SETTING", "TAVILY_API_KEY"]
    assert tool_env.grant(["TAVILY_API_KEY"]) == {"TAVILY_API_KEY": "tvly-quoted-value-123"}


def test_from_dotenv_explicit_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ToolEnv.from_dotenv(tmp_path / "nope.env")


def test_grant_names_missing_and_available():
    with pytest.raises(LookupError, match="GAMMA_API_KEY.*available"):
        env().grant(["GAMMA_API_KEY"])


# ---------------------------------------------------------------- redaction


def test_redact_raw_encoded_and_heuristics():
    special = "k3y+with/special=chars-0123456789"
    odd = "tok_" + "z" * 20
    tool_env = ToolEnv({
        "SVC_API_KEY": special,
        "ODD_NAME": odd,                                   # token-shaped value under a non-secret name
        "AUTH_MODE": "on",                                 # too short to redact
        "BASE_URL": "https://api.example.com/v1/long/path",  # URL, not a token
        "CITY": "San Francisco",
    })
    text = (f"{special} {quote(special, safe='')} {quote_plus(special)} {quote(special)} "
            f"{special.replace('/', chr(92) + '/')} {odd} on https://api.example.com/v1/long/path San Francisco")
    out = tool_env.redact(text)
    assert out.count("[REDACTED:SVC_API_KEY]") == 5
    assert "[REDACTED:ODD_NAME]" in out
    assert " on " in out and "https://api.example.com/v1/long/path" in out and "San Francisco" in out
    assert tool_env.leaked(out) == [] and tool_env.leaked(text) == ["SVC_API_KEY", "ODD_NAME"]
    assert tool_env.redact(None) is None


def test_redact_longest_first():
    tool_env = ToolEnv({"A_TOKEN": "abcdefgh1234", "B_TOKEN": "abcdefgh1234-extended"})
    assert tool_env.redact("abcdefgh1234-extended") == "[REDACTED:B_TOKEN]"


# ---------------------------------------------------------------- REQUIRED_ENV


@pytest.mark.parametrize(
    "code, expected",
    [
        ('REQUIRED_ENV = ["A", "B", "A"]', ["A", "B"]),
        ('REQUIRED_ENV = ("A",)', ["A"]),
        ('REQUIRED_ENV: list[str] = ["A"]', ["A"]),
        ("x = 1", []),
    ],
)
def test_required_env_parses_literals(code, expected):
    assert required_env(code) == expected


def test_required_env_rejects_non_literal():
    with pytest.raises(ValueError, match="literal"):
        required_env("import os\nREQUIRED_ENV = list(os.environ)")


# ---------------------------------------------------------------- process environment


def test_sandbox_env_drops_tool_env_names(monkeypatch):
    monkeypatch.setenv("PLAIN_SETTING", "hello")
    assert "PLAIN_SETTING" not in sandbox_env(drop=["PLAIN_SETTING"])
    assert sandbox_env({"PLAIN_SETTING": "x"}, drop=["PLAIN_SETTING"])["PLAIN_SETTING"] == "x"


def test_env_for_grants_only_declared(monkeypatch):
    monkeypatch.setenv("BETA_API_KEY", BETA)  # present in the parent env too: must still be dropped
    granted = env().env_for('REQUIRED_ENV = ["ALPHA_API_KEY"]', {"X_API_BASE": "http://x"})
    assert granted["ALPHA_API_KEY"] == ALPHA and granted["X_API_BASE"] == "http://x"
    assert "BETA_API_KEY" not in granted and "PLAIN_SETTING" not in granted
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python -m pytest tests/test_toolenv.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'autotool.core.toolenv'`.

- [ ] **Step 3: Add `drop` to `sandbox_env`** in `autotool/clients/dynamic_client.py`. Add `Iterable` to the `typing` import (`from typing import Any, Iterable, TextIO`) and replace the function:

```python
def sandbox_env(extra: dict[str, str] | None = None, drop: Iterable[str] = ()) -> dict[str, str]:
    """Parent environment minus secrets and minus ``drop`` (every .env tool variable, so a
    tool only sees the ones granted to it through ``extra``). Keeps PATH, proxy and CA
    settings so generated tools can still reach the network the host is allowed to reach."""
    dropped = {name.upper() for name in drop}
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV_RE.search(k) and k.upper() not in dropped}
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env
```

- [ ] **Step 4: Create `autotool/core/toolenv.py`:**

```python
"""Credentials and settings for synthesized tools, discovered from ``.env``.

The LLM only ever sees variable *names*. A tool declares the names it reads in a
module-level ``REQUIRED_ENV`` list; only those values are injected into its process,
and every secret value is redacted from text that flows back to the LLM."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

from dotenv import dotenv_values, find_dotenv

from autotool.clients.dynamic_client import sandbox_env

# Variables the runtime itself uses (LLM credentials, model ids, settings) are never offered to tools.
RESERVED_PREFIXES = ("OPENAI_", "ANTHROPIC_", "AUTOTOOL_")
_SECRET_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PRIVATE", re.IGNORECASE)
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DECL_ERROR = 'REQUIRED_ENV must be a module-level literal list of variable-name strings, e.g. REQUIRED_ENV = ["X_API_KEY"]'


def required_env(code: str) -> list[str]:
    """Names in the module-level ``REQUIRED_ENV`` list/tuple of string literals ([] if absent)."""
    for node in ast.parse(code).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "REQUIRED_ENV" for t in targets):
            continue
        try:
            names = ast.literal_eval(value)
        except ValueError:
            raise ValueError(_DECL_ERROR) from None
        if not isinstance(names, (list, tuple)) or not all(isinstance(n, str) for n in names):
            raise ValueError(_DECL_ERROR)
        return list(dict.fromkeys(names))
    return []


def _is_secret(name: str, value: str) -> bool:
    # ponytail: heuristic. Values under 8 chars are never redacted so `AUTH_MODE=on` can't
    # mangle output; odd-named secrets are caught by shape (long, no spaces, not a URL).
    if len(value) < 8:
        return False
    if _SECRET_NAME_RE.search(name):
        return True
    return len(value) >= 16 and not any(c.isspace() for c in value) and "://" not in value


def _secret_pattern(value: str) -> re.Pattern[str]:
    """Match ``value`` with any non-alphanumeric char raw, percent-encoded or backslash-escaped
    (JSON ``\\/``), and spaces as ``+``. Covers keys echoed inside URLs and JSON bodies."""
    parts = []
    for ch in value:
        if ch.isalnum():
            parts.append(re.escape(ch))
            continue
        alts = [re.escape(ch), re.escape("\\" + ch), re.escape("".join(f"%{b:02X}" for b in ch.encode()))]
        if ch == " ":
            alts.append(r"\+")
        parts.append("(?:" + "|".join(alts) + ")")
    return re.compile("".join(parts), re.IGNORECASE)


class ToolEnv:
    def __init__(self, values: dict[str, str | None] | None = None) -> None:
        self._values: dict[str, str] = {
            k: v
            for k, v in (values or {}).items()
            if v and _ENV_NAME_RE.match(k) and not k.upper().startswith(RESERVED_PREFIXES)
        }
        # Longest first, so a value containing another secret is replaced whole.
        ordered = sorted(((k, v) for k, v in self._values.items() if _is_secret(k, v)), key=lambda kv: -len(kv[1]))
        self._secrets = [(_secret_pattern(v), k) for k, v in ordered]

    @classmethod
    def from_dotenv(cls, path: str | Path | None = None) -> "ToolEnv":
        """Explicit ``path`` must exist; otherwise the nearest ``.env`` from the cwd, if any."""
        if path is None:
            found = find_dotenv(usecwd=True)
            return cls(dotenv_values(found)) if found else cls()
        if not Path(path).is_file():
            raise FileNotFoundError(f"env file not found: {path}")
        return cls(dotenv_values(path))

    @property
    def names(self) -> list[str]:
        return sorted(self._values)

    def grant(self, required: Iterable[str]) -> dict[str, str]:
        required = list(required)
        missing = [n for n in required if n not in self._values]
        if missing:
            raise LookupError(f"tool requires {missing}, which are not set in .env; available: {self.names or 'none'}")
        return {n: self._values[n] for n in required}

    def env_for(self, code: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Process environment for a tool: scrubbed parent env + overrides + only its declared vars."""
        return sandbox_env({**(overrides or {}), **self.grant(required_env(code))}, drop=self._values)

    def redact(self, text: str | None) -> str | None:
        if not text:
            return text
        for pattern, name in self._secrets:
            text = pattern.sub(f"[REDACTED:{name}]", text)
        return text

    def leaked(self, text: str) -> list[str]:
        """Names of secrets whose value appears in ``text`` in any encoding ``redact`` handles."""
        return [name for pattern, name in self._secrets if pattern.search(text)]
```

Note on `test_redact_raw_encoded_and_heuristics`: `leaked(text)` order follows value length (longest first): `special` is 33 chars and `odd` is 24, so `["SVC_API_KEY", "ODD_NAME"]`.

- [ ] **Step 5: Run the new tests and the whole suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all pass (23 existing + 12 new).

- [ ] **Step 6: Commit**

```bash
git -c safe.directory=* add autotool/core/toolenv.py autotool/clients/dynamic_client.py tests/test_toolenv.py
git -c safe.directory=* commit -m "Add ToolEnv: .env discovery, per-tool grants and secret redaction"
```

---

### Task 2: Verifier, static check, generator prompt

**Files:**
- Modify: `autotool/synthesis/verifier.py` (`static_check`, `ToolVerifier.__init__`, `ToolVerifier.verify`)
- Modify: `autotool/synthesis/generator.py` (`GENERATOR_SYSTEM`, `ToolGenerator`)
- Modify: `autotool/synthesis/repair.py` (`SynthesisEngine.__init__`)
- Test: `tests/test_toolenv.py` (append)

**Interfaces:**
- Consumes: `ToolEnv`, `required_env` from Task 1.
- Produces:
  - `static_check(code: str, available: Iterable[str] | None = None) -> str | None`
  - `ToolVerifier(staging_dir, *, timeout_s=15.0, env_overrides=None, tool_env: ToolEnv | None = None)` exposing `.tool_env`
  - `ToolGenerator(provider, env_names: list[str] | None = None)`

- [ ] **Step 1: Append the failing tests** to `tests/test_toolenv.py`. Add these imports at the top:

```python
from autotool.core.schema import CapabilityRequest
from autotool.synthesis.repair import SynthesisEngine
from autotool.synthesis.verifier import ToolVerifier, static_check
from tests.test_synthesis import GOOD, scripted_generator, server
```

and append:

```python
PROBE = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def probe() -> str:
        """List the test variables this process can see."""
        names = {"ALPHA_API_KEY", "BETA_API_KEY", "PLAIN_SETTING"}
        return ",".join(sorted(k for k in os.environ if k.upper() in names))
    ''',
    name="probe_tool",
)
LEAKY = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def leak() -> str:
        """Fail with the key in the message, like an HTTP error that includes the request URL."""
        raise RuntimeError(f"401 for url https://api.example.com/v1?key={os.environ['ALPHA_API_KEY']}")
    ''',
    name="leaky_tool",
)


# ---------------------------------------------------------------- static check / verifier


def test_static_check_rejects_unavailable_env():
    problem = static_check(PROBE, ["BETA_API_KEY"])
    assert problem and "ALPHA_API_KEY" in problem and "BETA_API_KEY" in problem
    assert static_check(PROBE, ["ALPHA_API_KEY"]) is None
    assert static_check(PROBE) is None  # no availability check requested


def test_static_check_rejects_non_literal_declaration():
    assert "literal" in static_check(GOOD.replace("mcp = FastMCP", "REQUIRED_ENV = list('x')\nmcp = FastMCP"), [])


async def test_verifier_injects_only_declared_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAIN_SETTING", "hello")  # also in the parent env: must still be dropped
    verifier = ToolVerifier(tmp_path / "stg", tool_env=env())
    report = await verifier.verify("probe_tool", PROBE, primary_tool="probe", smoke_arguments={})
    assert report.ok, report.failure_summary()
    assert report.smoke_output == "ALPHA_API_KEY"


async def test_verifier_redacts_secret_in_error_and_stderr(tmp_path):
    report = await ToolVerifier(tmp_path / "stg", tool_env=env()).verify(
        "leaky_tool", LEAKY, primary_tool="leak", smoke_arguments={}
    )
    assert not report.ok and report.stage == "smoke_test"
    assert "[REDACTED:ALPHA_API_KEY]" in report.error
    assert ALPHA not in report.error + report.stderr + report.failure_summary()


async def test_verifier_rejects_unavailable_var_before_launch(tmp_path):
    report = await ToolVerifier(tmp_path / "stg", tool_env=ToolEnv()).verify("probe_tool", PROBE)
    assert not report.ok and report.stage == "static" and "ALPHA_API_KEY" in report.error


async def test_generator_prompt_lists_names_not_values(tmp_path):
    provider, prompts = scripted_generator([GOOD])
    verifier = ToolVerifier(tmp_path / "stg", tool_env=env())
    engine = SynthesisEngine(provider, tools_dir=tmp_path / "tools", verifier=verifier)
    await engine.build_tool(CapabilityRequest(tool_name="math_tool", capability_description="add ints"))
    assert "ALPHA_API_KEY" in prompts[0] and "REQUIRED_ENV" in prompts[0]
    assert ALPHA not in prompts[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python -m pytest tests/test_toolenv.py -q`
Expected: new tests fail. `static_check()` rejects the extra argument with a TypeError, and `ToolVerifier` rejects the `tool_env` keyword.

- [ ] **Step 3: Update `autotool/synthesis/verifier.py`.** Imports: add `Iterable` to `from typing import Any, Iterable` and add `from autotool.core.toolenv import ToolEnv, required_env`. Change `from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result, sandbox_env` to `from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result`.

Change the `static_check` signature and docstring, and add the declaration check just before `return "; ".join(problems) or None`:

```python
def static_check(code: str, available: Iterable[str] | None = None) -> str | None:
    """Return an error message if the code violates the tool contract. ``available`` is the
    set of .env names a tool may declare in ``REQUIRED_ENV`` (None skips that check)."""
```

```python
    try:
        declared = required_env(code)
    except ValueError as exc:
        problems.append(str(exc))
    else:
        if available is not None:
            allowed = set(available)
            unknown = [n for n in declared if n not in allowed]
            if unknown:
                problems.append(
                    f"REQUIRED_ENV lists {unknown}, which are not available; available variables: {sorted(allowed) or 'none'}"
                )
    return "; ".join(problems) or None
```

`ToolVerifier.__init__` gains a parameter and attribute:

```python
    def __init__(
        self,
        staging_dir: str | Path = ".staging",
        *,
        timeout_s: float = 15.0,
        env_overrides: dict[str, str] | None = None,
        tool_env: ToolEnv | None = None,
    ) -> None:
        self.staging_dir = Path(staging_dir).resolve()
        self.timeout_s = timeout_s
        self.env_overrides = env_overrides or {}
        self.tool_env = tool_env or ToolEnv()
```

In `verify`, change the static check call, the client env, and redact the report before returning:

```python
        problem = static_check(code, self.tool_env.names)
```

```python
            client = DynamicMCPClient(
                path, server_name=tool_name, env=self.tool_env.env_for(code, self.env_overrides), errlog=errlog
            )
```

```python
            report.stderr = client.read_stderr()
        report.duration_s = time.monotonic() - started
        # Everything in the report can reach the LLM (repair prompt, events): scrub secret values.
        redact = self.tool_env.redact
        report.error, report.stderr, report.smoke_output = redact(report.error), redact(report.stderr), redact(report.smoke_output)
        return report
```

- [ ] **Step 4: Update `autotool/synthesis/generator.py`.** In `GENERATOR_SYSTEM`, replace these two lines:

```
- Use `httpx` with an explicit timeout of at most 10 seconds for network calls. Only use public,
  keyless APIs; never require or read API keys, tokens or other secrets.
```

with:

```
- Use `httpx` with an explicit timeout of at most 10 seconds for network calls. Use public APIs, or
  APIs whose credentials the prompt lists as available environment variables. Never hard-code
  credentials.
- Credentials: read each one with `os.environ["NAME"]` and declare every name you read at module
  level, e.g. `REQUIRED_ENV = ["NAME"]`. Only declared names are injected into the process. Send keys
  in headers when the API allows it; never return, log or put key values in error messages.
```

Replace the `ToolGenerator` constructor, and add the env section to both prompts. Build them exactly like this:

```python
class ToolGenerator:
    def __init__(self, provider: LLMProvider, env_names: list[str] | None = None) -> None:
        self.provider = provider
        self.env_names = env_names or []

    def _env_section(self) -> str:
        if not self.env_names:
            return "No credentials are available: only use public, keyless APIs and do not declare REQUIRED_ENV."
        return (
            "Environment variables available to this tool (values are injected at runtime; you never see them): "
            f"{', '.join(self.env_names)}.\nIf the API needs one of them, read it with os.environ[\"NAME\"] and "
            "declare it, e.g. REQUIRED_ENV = [\"NAME\"]. Declare only the ones this tool actually uses."
        )

    async def generate(self, request: CapabilityRequest) -> GeneratedToolCandidate:
        prompt = (
            f"Write the MCP server `{request.tool_name}` (use exactly `FastMCP(\"{request.tool_name}\")`).\n\n"
            f"Capability it must provide:\n{request.capability_description}\n\n"
            f"{self._env_section()}\n\n"
            f"Structural reference (adapt, do not copy the example API):\n```python\n{TEMPLATE}```"
        )
        return self._finalize(await self.provider.structured(system=GENERATOR_SYSTEM, prompt=prompt, output_model=GeneratedToolCandidate))
```

In `repair`, insert `f"{self._env_section()}\n\n"` directly after the `Capability it must provide` line.

- [ ] **Step 5: Wire the names into `SynthesisEngine`** (`autotool/synthesis/repair.py`). Create the verifier before the generator:

```python
        self.verifier = verifier or ToolVerifier()
        self.generator = ToolGenerator(provider, env_names=self.verifier.tool_env.names)
```

(Delete the old `self.generator = ToolGenerator(provider)` line and the old `self.verifier = ...` line.)

- [ ] **Step 6: Run the whole suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git -c safe.directory=* add autotool/synthesis tests/test_toolenv.py
git -c safe.directory=* commit -m "Verify and generate tools against .env credentials with per-tool REQUIRED_ENV"
```

---

### Task 3: Registry, orchestrator, CLI, docs + end-to-end test

**Files:**
- Modify: `autotool/core/registry.py`, `autotool/core/orchestrator.py`, `autotool/main.py`, `README.md`
- Test: `tests/test_toolenv.py` (append)

**Interfaces:**
- Consumes: `ToolEnv` (Task 1), `ToolVerifier(tool_env=...)` (Task 2).
- Produces:
  - `ToolRegistry(tools_dir, *, call_timeout_s=30.0, env_overrides=None, tool_env: ToolEnv | None = None)` exposing `.tool_env`
  - `system_prompt(env_names: list[str]) -> str` in `autotool/core/orchestrator.py`
  - `run_objective(..., tool_env: ToolEnv | None = None)`; `None` means discover `.env`
  - CLI flag `--env-file`

- [ ] **Step 1: Append the failing tests** to `tests/test_toolenv.py`. Add imports:

```python
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from autotool.core.llm import ScriptedProvider
from autotool.core.orchestrator import SYNTHESIZE_TOOL, SYSTEM_PROMPT, Orchestrator, system_prompt
from autotool.core.registry import ToolRegistry
from autotool.core.schema import GeneratedToolCandidate, LLMTurn, ToolCall
```

Then append:

```python
def probe_server(name: str, var: str) -> str:
    return server(
        f'''
        import os

        REQUIRED_ENV = ["{var}"]

        @mcp.tool()
        def probe() -> str:
            """List the credential variables this process can see."""
            return ",".join(sorted(k for k in os.environ if k.upper().endswith("_API_KEY")))
        ''',
        name=name,
    )


ECHO = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def echo() -> str:
        """Return the key (a badly behaved tool)."""
        return "key=" + os.environ["ALPHA_API_KEY"]
    ''',
    name="echo_tool",
)


# ---------------------------------------------------------------- registry


async def test_registry_gives_each_tool_only_its_own_key(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "tavily_tool.py").write_text(probe_server("tavily_tool", "TAVILY_API_KEY"))
    (tools_dir / "composio_tool.py").write_text(probe_server("composio_tool", "COMPOSIO_API_KEY"))
    tool_env = ToolEnv({"TAVILY_API_KEY": "tvly-" + "t" * 20, "COMPOSIO_API_KEY": "cmp-" + "c" * 20})
    async with ToolRegistry(tools_dir, tool_env=tool_env) as registry:
        assert await registry.load_cached() == ["composio_tool", "tavily_tool"]
        assert (await registry.call("1", "tavily_tool__probe", {})).content == "TAVILY_API_KEY"
        assert (await registry.call("2", "composio_tool__probe", {})).content == "COMPOSIO_API_KEY"


async def test_registry_skips_cached_tool_whose_var_is_gone(tmp_path, caplog):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "tavily_tool.py").write_text(probe_server("tavily_tool", "TAVILY_API_KEY"))
    async with ToolRegistry(tools_dir, tool_env=ToolEnv()) as registry:
        assert await registry.load_cached() == []
    assert "TAVILY_API_KEY" in caplog.text


async def test_registry_redacts_tool_output(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "echo_tool.py").write_text(ECHO)
    async with ToolRegistry(tools_dir, tool_env=env()) as registry:
        await registry.load_cached()
        result = await registry.call("1", "echo_tool__echo", {})
    assert result.content == "key=[REDACTED:ALPHA_API_KEY]"


def test_system_prompt_lists_names_only_when_present():
    assert system_prompt([]) == SYSTEM_PROMPT
    prompt = system_prompt(["TAVILY_API_KEY"])
    assert "TAVILY_API_KEY" in prompt and prompt.startswith(SYSTEM_PROMPT)


# ---------------------------------------------------------------- end to end: Bearer-auth API

BEARER = "k3y+with/special=" + secrets.token_hex(8)  # URL-reserved chars on purpose


class _BearerAPI(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {BEARER}":
            return self._send(401, {"error": "unauthorized"})
        city = parse_qs(urlparse(self.path).query).get("city", ["?"])[0]
        self._send(200, {"city": city, "temp_c": 21})

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def bearer_api():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _BearerAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


WEATHER_TOOL = server(
    '''
    import os

    import httpx

    REQUIRED_ENV = ["ACME_API_KEY"]
    API_BASE = os.environ.get("ACME_API_BASE", "https://api.acme.example")

    @mcp.tool()
    def current(city: str) -> str:
        """Current weather for a city."""
        with httpx.Client(timeout=10) as client:
            AUTH_LINE
            resp.raise_for_status()
            return resp.text
    ''',
    name="acme_tool",
)
# First draft puts the key in the query string (the server wants a header), so the 401
# error URL carries the key percent-encoded into the repair prompt unless redacted.
QUERY_DRAFT = WEATHER_TOOL.replace(
    "AUTH_LINE", 'resp = client.get(f"{API_BASE}/weather", params={"city": city, "key": os.environ["ACME_API_KEY"]})'
)
HEADER_DRAFT = WEATHER_TOOL.replace(
    "AUTH_LINE",
    'resp = client.get(f"{API_BASE}/weather", params={"city": city}, '
    'headers={"Authorization": "Bearer " + os.environ["ACME_API_KEY"]})',
)


class Recording(ScriptedProvider):
    """Scripted provider that also keeps every string it would send to an LLM."""

    def __init__(self, chat, structured) -> None:
        super().__init__(chat, structured)
        self.sent: list[str] = []

    async def complete(self, *, system, messages, tools):
        self.sent.append(json.dumps([system, messages, tools], default=str))
        return await super().complete(system=system, messages=messages, tools=tools)

    async def structured(self, *, system, prompt, output_model):
        self.sent.append(system + "\n" + prompt)
        return await super().structured(system=system, prompt=prompt, output_model=output_model)


async def test_end_to_end_bearer_api_repairs_without_leaking(tmp_path, bearer_api):
    drafts = iter([QUERY_DRAFT, HEADER_DRAFT])
    turns = 0

    def chat(messages, tools):
        nonlocal turns
        turns += 1
        if turns == 1:
            return LLMTurn(tool_calls=[ToolCall(id="s1", name=SYNTHESIZE_TOOL, arguments={
                "tool_name": "acme_tool", "capability_description": "Current weather from the Acme API (ACME_API_KEY)."})])
        if turns == 2:
            return LLMTurn(tool_calls=[ToolCall(id="c1", name="acme_tool__current", arguments={"city": "Paris"})])
        return LLMTurn(text=messages[-1]["content"][0]["content"])

    def structured(prompt, model):
        return GeneratedToolCandidate(code=next(drafts), primary_tool="current", smoke_test_arguments_json='{"city": "Paris"}')

    provider = Recording(chat, structured)
    tool_env = ToolEnv({"ACME_API_KEY": BEARER})
    overrides = {"ACME_API_BASE": bearer_api}
    tools_dir = tmp_path / "tools"
    verifier = ToolVerifier(tmp_path / "stg", env_overrides=overrides, tool_env=tool_env)
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=verifier)
    async with ToolRegistry(tools_dir, env_overrides=overrides, tool_env=tool_env) as registry:
        run = await Orchestrator(provider, registry, engine).run("Weather in Paris?")

    assert json.loads(run.answer) == {"city": "Paris", "temp_c": 21}
    synth = next(e.detail for e in run.events if e.kind == "synthesis")
    assert synth["ok"] and synth["attempts"] == 2
    sent = "\n".join(provider.sent)
    assert "ACME_API_KEY" in sent                # the name reaches the LLM ...
    assert "[REDACTED:ACME_API_KEY]" in sent     # ... the failed draft's error URL was scrubbed ...
    assert tool_env.leaked(sent) == []           # ... and no encoding of the value got through
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python -m pytest tests/test_toolenv.py -q`
Expected: collection fails with `ImportError: cannot import name 'system_prompt'`.

- [ ] **Step 3: Update `autotool/core/registry.py`.** Change the import to `from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result` and add `from autotool.core.toolenv import ToolEnv`. Add `tool_env: ToolEnv | None = None` to `__init__` (after `env_overrides`), and store it with `self.tool_env = tool_env or ToolEnv()`. In `mount`, replace the client construction:

```python
        # Least privilege: the process gets only the .env variables this script declares.
        env = self.tool_env.env_for(path.read_text(encoding="utf-8"), self.env_overrides)
        client = DynamicMCPClient(path, server_name=name, env=env, call_timeout_s=self.call_timeout_s)
```

In `call`, redact both return paths:

```python
        except Exception as exc:  # noqa: BLE001 - surface to the LLM, keep running
            return ToolResult(
                call_id=call_id, content=self.tool_env.redact(f"Tool call failed: {type(exc).__name__}: {exc}"), is_error=True
            )
        content = self.tool_env.redact(render_call_result(result) or "(empty result)")
        return ToolResult(call_id=call_id, content=content, is_error=result.isError)
```

- [ ] **Step 4: Update `autotool/core/orchestrator.py`.** Add after `SYSTEM_PROMPT`:

```python
def system_prompt(env_names: list[str]) -> str:
    """SYSTEM_PROMPT plus the names (never values) of credentials synthesized tools may use."""
    if not env_names:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + (
        "\n- Credentials and settings are available to tools you synthesize (values are injected at runtime "
        f"and never shown to you): {', '.join(env_names)}. When a task needs a service one of these unlocks, "
        "synthesize a tool for it and name the variable(s) in capability_description. If a task needs "
        "credentials that are not listed, say which are missing instead of guessing."
    )
```

In `Orchestrator.run`, compute `system = system_prompt(self.registry.tool_env.names)` before the loop and pass `system=system` to `self.provider.complete` in place of `system=SYSTEM_PROMPT`.

- [ ] **Step 5: Update `autotool/main.py`.** Add `from autotool.core.toolenv import ToolEnv`. Add the `run_objective` parameter `tool_env: ToolEnv | None = None` after `env_overrides`, then start the body with:

```python
    tool_env = tool_env if tool_env is not None else ToolEnv.from_dotenv()
    verifier = ToolVerifier(staging_dir, timeout_s=timeout_s, env_overrides=env_overrides, tool_env=tool_env)
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=verifier, max_retries=max_retries)
    async with ToolRegistry(tools_dir, env_overrides=env_overrides, tool_env=tool_env) as registry:
        cached = await registry.load_cached()
        if verbose:
            print(f"Tool credentials from .env: {tool_env.names or 'none'}", file=sys.stderr)
            print(f"Mounted {len(cached)} cached tool server(s): {cached or 'none'}", file=sys.stderr)
```

In `cli`, add `parser.add_argument("--env-file", default=None, help="dotenv file whose variables synthesized tools may use (default: nearest .env)")` and pass `tool_env=ToolEnv.from_dotenv(args.env_file)` to `run_objective`.

- [ ] **Step 6: README.** In `README.md`, add under `## Notes` (first bullet), replacing the first sentence of the existing env bullet so the two agree:

```markdown
- **Credentials for generated tools come from `.env`.** Add any variable (`TAVILY_API_KEY=...`,
  `COMPOSIO_API_KEY=...`, `MY_SERVICE_BASE_URL=...`) and the agent sees its *name*, never its value,
  and can synthesize a tool that uses it. A tool declares what it reads (`REQUIRED_ENV = ["TAVILY_API_KEY"]`)
  and its process receives only those variables; every other `.env` variable is stripped. Secret values
  are redacted (`[REDACTED:NAME]`) from tool output and verifier errors before they reach the LLM.
  Variables starting with `OPENAI_`, `ANTHROPIC_` or `AUTOTOOL_` are reserved for the runtime and never
  offered to tools. Use `--env-file` to point at another file.
- Beyond the declared variables, generated tools run with a scrubbed environment: ...
```

(Keep the rest of the existing bullet's text after "scrubbed environment:".)

- [ ] **Step 7: Run the whole suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all pass. If the end-to-end test reports a leak, the httpx URL encoding produced a form that `_secret_pattern` misses. Print `sent`, find the form, and extend `_secret_pattern` rather than weakening the test.

- [ ] **Step 8: Commit**

```bash
git -c safe.directory=* add autotool README.md tests/test_toolenv.py
git -c safe.directory=* commit -m "Mount tools with least-privilege .env grants, redact tool output, surface names to the agent"
```

---

### Task 4: Live benchmark `scripts/auth_benchmark.py`

**Files:**
- Create: `scripts/auth_benchmark.py`

**Interfaces:**
- Consumes: `run_objective(..., tool_env=...)` (Task 3), `ToolEnv.leaked`, `required_env` (Task 1), `default_provider`.
- Produces: `results/auth-<stamp>.json` and `results/auth-<stamp>.md`. JSON rows have the keys `task, suite, condition, trial, passed, grade_note, answer, steps, synthesized, attempts, synth_ok, tool_errors, declared_env, expected_env, env_match, overprivileged, leaks, redactions, wall_s, llm_calls, input_tokens, output_tokens, error`.

- [ ] **Step 1: Write the script:**

```python
"""Benchmark authenticated tool synthesis (credentials discovered from .env).

Suites
  mock     Local API with four auth schemes (custom header, Bearer, query parameter, HTTP Basic)
           and fresh random credentials and data every run. Objectives document the endpoint and
           the scheme but never name the environment variable: the agent must map the service to
           the right variable itself. A decoy credential checks least privilege.
  real     Tavily and Composio with TAVILY_API_KEY / COMPOSIO_API_KEY from .env. Objectives never
           name Tavily. Graded against ground truth fetched directly at grading time.
  control  A service with no credential available (Stripe): the agent must say what is missing.

Conditions
  env       tool credentials discovered from .env (plus the mock credentials)
  ablation  no tool credentials, i.e. the previous AutoTool behaviour

Every string sent to the LLM is recorded and scanned for every secret value in any
percent-/escape-encoding (ToolEnv.leaked). Results: results/auth-<stamp>.json and .md.

    python scripts/auth_benchmark.py --trials 3
    python scripts/auth_benchmark.py --suites mock --conditions env --trials 1 -v
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import dotenv_values, find_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autotool.core.llm import default_provider  # noqa: E402
from autotool.core.toolenv import ToolEnv, required_env  # noqa: E402
from autotool.main import run_objective  # noqa: E402

SALT = secrets.token_hex(4)  # per-run data, so answers cannot come from memory
CITIES = ["Oslo", "Lima", "Hanoi", "Perth", "Quito", "Dakar", "Tallinn", "Cusco"]
MOCK = {
    "NIMBUS_API_KEY": "nb_" + secrets.token_urlsafe(18),
    "LEDGERLY_TOKEN": "lg_" + secrets.token_urlsafe(24),
    "QUOTIENT_API_KEY": "qt+" + secrets.token_urlsafe(12) + "/=",  # URL-reserved chars on purpose
    "PARCELLY_USERNAME": "acct-" + secrets.token_hex(4),
    "PARCELLY_PASSWORD": "pw!" + secrets.token_urlsafe(12),
    "UNUSED_SERVICE_TOKEN": "decoy_" + secrets.token_urlsafe(18),  # no task needs it
}


def _num(seed: str, lo: int, hi: int) -> int:
    return lo + int(hashlib.sha256(f"{SALT}:{seed}".encode()).hexdigest(), 16) % (hi - lo + 1)


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", text)]


# ---------------------------------------------------------------- local mock API


def nimbus_temp(city: str) -> int:
    return _num("nimbus" + city.lower(), -9, 38)


def ledgerly_cents(account: str) -> int:
    return _num("ledgerly" + account.upper(), 10_000, 9_999_999)


def quotient_price(symbol: str) -> int:
    return _num("quotient" + symbol.upper(), 12, 4_999)


def parcelly_city(number: str) -> str:
    return CITIES[_num("parcelly" + number.upper(), 0, len(CITIES) - 1)]


class _MockAPI(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = url.path.strip("/").split("/")
        h = self.headers
        basic = "Basic " + base64.b64encode(f"{MOCK['PARCELLY_USERNAME']}:{MOCK['PARCELLY_PASSWORD']}".encode()).decode()
        if url.path == "/nimbus/v1/current":
            if h.get("X-Nimbus-Key") != MOCK["NIMBUS_API_KEY"]:
                return self._send(401, {"error": "missing or invalid X-Nimbus-Key"})
            city = q.get("city", "")
            return self._send(200, {"city": city, "temperature_c": nimbus_temp(city), "condition": "overcast"})
        if parts[:3] == ["ledgerly", "v2", "accounts"] and len(parts) == 5 and parts[4] == "balance":
            if h.get("Authorization") != f"Bearer {MOCK['LEDGERLY_TOKEN']}":
                return self._send(401, {"error": "invalid bearer token"})
            return self._send(200, {"account_id": parts[3], "balance_cents": ledgerly_cents(parts[3]), "currency": "EUR"})
        if url.path == "/quotient/v1/quote":
            if q.get("apikey") != MOCK["QUOTIENT_API_KEY"]:
                return self._send(401, {"error": "invalid apikey"})
            sym = q.get("symbol", "")
            return self._send(200, {"symbol": sym.upper(), "price_usd": quotient_price(sym)})
        if parts[:3] == ["parcelly", "api", "track"] and len(parts) == 4:
            if h.get("Authorization") != basic:
                return self._send(401, {"error": "basic auth required"})
            return self._send(200, {"tracking_number": parts[3], "status": "in_transit", "last_scan_city": parcelly_city(parts[3])})
        self._send(404, {"error": "not found"})

    def _send(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


def start_mock() -> str:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


# ---------------------------------------------------------------- tasks


@dataclass
class Task:
    key: str
    suite: str
    prompt: str
    grade: Callable[[str], tuple[bool, str]]
    expected_env: list[str] = field(default_factory=list)


def _get(url: str, **kw: Any) -> Any:
    r = httpx.get(url, timeout=15, follow_redirects=True, **kw)
    r.raise_for_status()
    return r.json()


def mock_tasks(base: str) -> list[Task]:
    def has(value: str) -> Callable[[str], tuple[bool, str]]:
        return lambda a: (value.lower() in a.lower(), f"expected {value}")

    def near(target: float, tol: float) -> Callable[[str], tuple[bool, str]]:
        return lambda a: (any(abs(n - target) <= tol for n in _numbers(a)), f"expected {target}")

    cents = ledgerly_cents("ACC-4471")
    return [
        Task("nimbus_header", "mock",
             f"The Nimbus Weather API is at {base}/nimbus/v1. GET /current?city=<name> returns current conditions; "
             "requests must carry the account's API key in an X-Nimbus-Key header. What is the current temperature "
             "in Reykjavik according to Nimbus?",
             near(nimbus_temp("Reykjavik"), 0), ["NIMBUS_API_KEY"]),
        Task("ledgerly_bearer", "mock",
             f"The Ledgerly accounting API is at {base}/ledgerly/v2 and uses Bearer-token authentication. "
             "GET /accounts/<id>/balance returns the balance in cents. What is the balance of account ACC-4471 in euros?",
             lambda a: (any(abs(n - cents / 100) < 0.01 or n == cents for n in _numbers(a)), f"expected {cents / 100:.2f}"),
             ["LEDGERLY_TOKEN"]),
        Task("quotient_query", "mock",
             f"The Quotient market-data API is at {base}/quotient/v1. GET /quote?symbol=<ticker>&apikey=<key> returns "
             "the latest price. What is the latest price of ZNTH?",
             near(quotient_price("ZNTH"), 0), ["QUOTIENT_API_KEY"]),
        Task("parcelly_basic", "mock",
             f"Parcelly's tracking API is at {base}/parcelly/api and uses HTTP Basic authentication with the account "
             "username and password. GET /track/<number> returns shipment status. Where was parcel PX-99812 last scanned?",
             has(parcelly_city("PX-99812")), ["PARCELLY_USERNAME", "PARCELLY_PASSWORD"]),
    ]


def real_tasks(keys: dict[str, str]) -> list[Task]:
    def grade_urls(answer: str) -> tuple[bool, str]:
        urls = list(dict.fromkeys(u.rstrip(").,]>") for u in re.findall(r"https?://[^\s)\]>\"']+", answer)))
        live = 0
        for u in urls[:5]:
            try:
                live += httpx.get(u, timeout=10, follow_redirects=True).status_code not in (404, 410)
            except httpx.HTTPError:
                pass
        return live >= 2, f"{live} live URL(s) of {len(urls)}"

    def grade_node(answer: str) -> tuple[bool, str]:
        versions = [v["version"].lstrip("v") for v in _get("https://nodejs.org/dist/index.json")[:3]]
        return any(v in answer for v in versions), f"expected one of {versions}"

    def composio_count(slug: str) -> Callable[[str], tuple[bool, str]]:
        def grade(answer: str) -> tuple[bool, str]:
            data = _get(f"https://backend.composio.dev/api/v3.1/toolkits/{slug}", headers={"x-api-key": keys["COMPOSIO_API_KEY"]})
            count = data.get("tools_count") or (data.get("meta") or {}).get("tools_count")
            return count is not None and count in _numbers(answer), f"expected {count}"
        return grade

    tasks = []
    if "TAVILY_API_KEY" in keys:
        tasks += [
            Task("websearch_news", "real",
                 "Find three recent web articles about the James Webb Space Telescope and give their titles and URLs.",
                 grade_urls, ["TAVILY_API_KEY"]),
            Task("websearch_fact", "real", "Search the web: what is the latest released version of Node.js?",
                 grade_node, ["TAVILY_API_KEY"]),
        ]
    if "COMPOSIO_API_KEY" in keys:
        tasks += [
            Task(f"composio_{slug}", "real", f"How many tools does the {slug.capitalize()} toolkit have on Composio?",
                 composio_count(slug), ["COMPOSIO_API_KEY"])
            for slug in ("github", "gmail")
        ]
    return tasks


def control_tasks() -> list[Task]:
    missing = re.compile(r"api key|credential|secret key|not (?:available|configured|set|provided)|missing|no access", re.I)

    def grade(answer: str) -> tuple[bool, str]:
        ok = bool(missing.search(answer)) and not re.search(r"\bch_[A-Za-z0-9]{8,}", answer)
        return ok, "expected an explanation that Stripe credentials are missing, and no invented charges"

    return [Task("stripe_missing", "control", "List my three most recent Stripe charges with their amounts.", grade)]


# ---------------------------------------------------------------- recording provider


class RecordingProvider:
    """Wraps a real provider and keeps every string sent to the LLM."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.sent: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def complete(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        self.sent.append(json.dumps({"system": system, "messages": messages, "tools": tools}, default=str))
        return await self.inner.complete(system=system, messages=messages, tools=tools)

    async def structured(self, *, system: str, prompt: str, output_model: type) -> Any:
        self.sent.append(system + "\n" + prompt)
        return await self.inner.structured(system=system, prompt=prompt, output_model=output_model)


# ---------------------------------------------------------------- runner


async def run_one(task: Task, condition: str, tool_values: dict[str, str], detector: ToolEnv, args: argparse.Namespace, out: Path, stamp: str, trial: int) -> dict[str, Any]:
    provider = RecordingProvider(default_provider(args.provider, args.model, reasoning_effort=args.reasoning_effort))
    tool_env = ToolEnv(tool_values if condition == "env" else {})
    root = Path(tempfile.mkdtemp(prefix=f"autotool-auth-{task.key}-"))
    row: dict[str, Any] = {"task": task.key, "suite": task.suite, "condition": condition, "trial": trial,
                           "model": provider.model, "expected_env": task.expected_env}
    started = time.monotonic()
    answer, code = "", ""
    try:
        result = await run_objective(task.prompt, provider=provider, tools_dir=str(root / "tools"),
                                     staging_dir=str(root / "stg"), tool_env=tool_env, verbose=args.verbose)
        answer = result.answer
        synth = [e.detail for e in result.events if e.kind == "synthesis"]
        passed, note = task.grade(answer)
        row.update(passed=passed, grade_note=note, answer=answer, steps=result.steps, synthesized=result.synthesized,
                   attempts=sum(s.get("attempts") or 0 for s in synth), synth_ok=all(s.get("ok") for s in synth) if synth else None,
                   tool_errors=sum(1 for e in result.events if e.kind == "tool_result" and e.detail["is_error"]), error=None)
    except Exception as exc:  # noqa: BLE001 - record and continue
        row.update(passed=False, grade_note=None, answer=answer, error=f"{type(exc).__name__}: {exc}"[:800])
    finally:
        declared: dict[str, list[str]] = {}
        for p in sorted((root / "tools").glob("*.py")):
            code += p.read_text(encoding="utf-8")
            try:
                declared[p.stem] = required_env(p.read_text(encoding="utf-8"))
            except (ValueError, SyntaxError):
                declared[p.stem] = ["<invalid>"]
        if args.keep_tools:
            shutil.copytree(root / "tools", out / f"auth-tools-{stamp}" / f"{task.key}-{condition}-{trial}", dirs_exist_ok=True)
        shutil.rmtree(root, ignore_errors=True)

    all_declared = {n for names in declared.values() for n in names}
    sent = "\n".join(provider.sent)
    row.update(
        declared_env=declared,
        env_match=(all_declared == set(task.expected_env)) if condition == "env" else None,
        overprivileged=sorted(all_declared - set(task.expected_env)),
        leaks=detector.leaked(sent + "\n" + answer + "\n" + code),
        redactions=sent.count("[REDACTED:"),
        wall_s=round(time.monotonic() - started, 2),
        llm_calls=provider.usage.calls, input_tokens=provider.usage.input_tokens, output_tokens=provider.usage.output_tokens,
    )
    return row


def summarize(rows: list[dict[str, Any]]) -> str:
    def mean(xs: list[Any]) -> str:
        xs = [x for x in xs if x is not None]
        return f"{sum(xs) / len(xs):.1f}" if xs else "–"

    lines = [
        "| task | suite | condition | pass | env match | over-privileged | leaks | redactions | mean attempts | mean wall s | mean tokens in/out |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for task, cond in dict.fromkeys((r["task"], r["condition"]) for r in rows):
        rs = [r for r in rows if r["task"] == task and r["condition"] == cond]
        match = [r["env_match"] for r in rs if r["env_match"] is not None]
        lines.append(
            f"| {task} | {rs[0]['suite']} | {cond} | {sum(r['passed'] for r in rs)}/{len(rs)} | "
            f"{f'{sum(match)}/{len(match)}' if match else '–'} | {sum(bool(r['overprivileged']) for r in rs)} | "
            f"{sum(len(r['leaks']) for r in rs)} | {sum(r['redactions'] for r in rs)} | {mean([r.get('attempts') for r in rs])} | "
            f"{mean([r['wall_s'] for r in rs])} | {mean([r['input_tokens'] for r in rs])}/{mean([r['output_tokens'] for r in rs])} |"
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suites", nargs="*", default=["mock", "real", "control"])
    parser.add_argument("--conditions", nargs="*", default=["env", "ablation"])
    parser.add_argument("--tasks", nargs="*", default=None, help="task keys to run (default: all in the suites)")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--out", default=str(ROOT / "results"))
    parser.add_argument("--keep-tools", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    env_file = args.env_file or find_dotenv(usecwd=True)
    dot = {k: v for k, v in dotenv_values(env_file).items() if v} if env_file else {}
    tool_values = {**ToolEnv(dot).grant(ToolEnv(dot).names), **MOCK}
    # Detector: every secret value in play, including the runtime's own keys (renamed past the reserved prefixes).
    detector = ToolEnv({**{f"SCAN_{k}": v for k, v in dot.items()}, **MOCK})

    tasks: list[Task] = []
    if "mock" in args.suites:
        tasks += mock_tasks(start_mock())
    if "real" in args.suites:
        tasks += real_tasks(tool_values)
    if "control" in args.suites:
        tasks += control_tasks()
    if args.tasks:
        tasks = [t for t in tasks if t.key in args.tasks]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"tasks={[t.key for t in tasks]} conditions={args.conditions} trials={args.trials} "
          f"tool env names={sorted(tool_values)}", file=sys.stderr)
    rows: list[dict[str, Any]] = []
    for task in tasks:
        for cond in args.conditions:
            for trial in range(1, args.trials + 1):
                row = await run_one(task, cond, tool_values, detector, args, out, stamp, trial)
                rows.append(row)
                print(f"[{task.key} {cond} #{trial}] {'PASS' if row['passed'] else 'FAIL'} {row['wall_s']}s "
                      f"declared={row['declared_env']} leaks={row['leaks']} redactions={row['redactions']} "
                      f"{row.get('error') or row.get('grade_note')}", file=sys.stderr)
                (out / f"auth-{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    table = summarize(rows) if rows else "(no results)"
    (out / f"auth-{stamp}.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

- [ ] **Step 2: Smoke run on the mock suite (live LLM, one trial)**

Run: `venv/Scripts/python scripts/auth_benchmark.py --suites mock --conditions env --trials 1 -v`
Expected:
- It completes and writes `results/auth-*.json` and `.md`.
- `leaks=[]` on every row.
- Most rows PASS with `declared` equal to the expected variable.

Fix script bugs (not the runtime) until it runs cleanly. If a runtime bug appears, add a failing test to `tests/test_toolenv.py` first, then fix it.

- [ ] **Step 3: Smoke the real and control suites (one trial)**

Run: `venv/Scripts/python scripts/auth_benchmark.py --suites real control --conditions env --trials 1 -v`
Expected:
- It completes.
- Composio ground truth resolves; if `tools_count` is `None`, inspect the response keys and adjust `composio_count`.
- `leaks=[]` on every row.

- [ ] **Step 4: Commit**

```bash
git -c safe.directory=* add scripts/auth_benchmark.py
git -c safe.directory=* commit -m "Add authenticated-synthesis benchmark: mock auth schemes, Tavily/Composio, leak audit"
```

---

### Task 5: Full evaluation run and paper

**Files:**
- Create: `paper/autotool-credentials.md`
- Create: `paper/results/` (a copy of the run's `.json` and `.md`; `results/` itself is gitignored)

- [ ] **Step 1: Full run** (in the background, about 1 hour):

Run: `venv/Scripts/python scripts/auth_benchmark.py --trials 3 --keep-tools`
Then copy `results/auth-<stamp>.json` and `.md` into `paper/results/`. Before committing, grep the copies for each secret with a small Python check: `ToolEnv({f"S_{k}": v for k, v in dotenv_values('.env').items() if v}).leaked(text) == []`. Do not commit if anything is found.

- [ ] **Step 2: Offline numbers.** Run `venv/Scripts/python -m pytest -q` and record the pass count and duration for the paper.

- [ ] **Step 3: Write `paper/autotool-credentials.md`** with these sections, filled with the measured numbers from `paper/results/` (no invented figures):
  1. Abstract
  2. Introduction: self-synthesizing agents stop at the authentication wall
  3. Background: the AutoTool pipeline before this change
  4. Design:
     - discovery
     - names-not-values
     - `REQUIRED_ENV` least privilege
     - encoding-aware redaction
     - agent and generator prompts
  5. Threat model: which attackers it covers, and which it explicitly does not (malicious generated code, prompt injection, egress)
  6. Evaluation setup:
     - suites
     - conditions
     - metrics
     - model and date
  7. Results:
     - the summary table
     - per-scheme analysis
     - redaction events
     - least privilege
     - ablation
     - negative control
     - cost
  8. Limitations and future work:
     - per-secret host allowlists
     - OAuth
     - base64 and other encodings
     - one model
     - small n
  9. Conclusion
  10. Reproducibility: commands and commit hash

- [ ] **Step 4: Commit**

```bash
git -c safe.directory=* add paper
git -c safe.directory=* commit -m "Add paper on authenticated tool synthesis with evaluation results"
```
