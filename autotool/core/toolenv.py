"""Credentials and settings for synthesized tools, discovered from ``.env``.

The LLM only ever sees variable *names*. A tool declares the names it reads in a
module-level ``REQUIRED_ENV`` list; only those values are injected into its process,
and every secret value is redacted from text that flows back to the LLM."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv

from autotool.clients.dynamic_client import sandbox_env
from autotool.core.policy import code_hash

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


def runtime_dotenv_path() -> str:
    """The .env that llm.py's load_dotenv() puts into os.environ. find_dotenv() called from this
    module walks up from the package, resolving the same file ("" if none)."""
    return find_dotenv()


def runtime_dotenv_names() -> list[str]:
    """Names in that file: tools must not inherit them."""
    found = runtime_dotenv_path()
    return list(dotenv_values(found)) if found else []


def _is_secret(name: str, value: str) -> bool:
    # A heuristic. Values under 8 chars are never redacted so `AUTH_MODE=on` can't
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
    def __init__(
        self,
        values: dict[str, str | None] | None = None,
        also_drop: Iterable[str] = (),
        *,
        hosts: dict[str, list[str]] | None = None,
        approvals: dict[str, dict[str, Any]] | None = None,
        protect: Iterable[str | Path] = (),
        guard: bool = True,
    ) -> None:
        """``hosts``: per-key allowlists. ``approvals``: tool -> approved keys, or None when consent
        is off. ``protect``: credential files a guarded tool may not read. ``guard``: run tools under
        autotool.guard (off when AutoTool itself already runs in a sandbox)."""
        values = values or {}
        self.hosts = hosts or {}
        self.approvals = approvals
        self.protect = [str(p) for p in protect]
        self.guard = guard
        # Every name from the source file(s), offered or not (reserved, empty, invalid), is stripped
        # from a tool's inherited environment: the runtime load_dotenv()s them into os.environ.
        self._drop = set(values) | set(also_drop)
        self._values: dict[str, str] = {
            k: v for k, v in values.items() if v and _ENV_NAME_RE.match(k) and not k.upper().startswith(RESERVED_PREFIXES)
        }
        # Reserved values (the runtime's model keys) are never granted, but still redacted: a tool can
        # read the file they came from. Longest first, so a value containing another is replaced whole.
        known = {k: v for k, v in values.items() if v and _ENV_NAME_RE.match(k)}
        ordered = sorted(((k, v) for k, v in known.items() if _is_secret(k, v)), key=lambda kv: -len(kv[1]))
        self._secrets = [(_secret_pattern(v), k) for k, v in ordered]

    @classmethod
    def from_dotenv(cls, path: str | Path | None = None) -> ToolEnv:
        """Explicit ``path`` must exist; otherwise the nearest ``.env`` from the cwd, if any."""
        runtime_names = runtime_dotenv_names()
        protect = [p for p in (runtime_dotenv_path(),) if p]
        if path is None:
            path = find_dotenv(usecwd=True)
            if not path:
                return cls(also_drop=runtime_names, protect=protect)
        elif not Path(path).is_file():
            raise FileNotFoundError(f"env file not found: {path}")
        return cls(dotenv_values(path), also_drop=runtime_names, protect=[*protect, path])

    @property
    def names(self) -> list[str]:
        return sorted(self._values)

    def grant(self, required: Iterable[str]) -> dict[str, str]:
        required = list(required)
        missing = [n for n in required if n not in self._values]
        if missing:
            raise LookupError(f"tool requires {missing}, which are not set in .env; available: {self.names or 'none'}")
        return {n: self._values[n] for n in required}

    def allowed_hosts(self, keys: Iterable[str]) -> list[str] | None:
        """Hosts a tool holding ``keys`` may reach: the union of its restricted keys' allowlists,
        or None (unrestricted) when none of its keys has one."""
        keys = [k for k in keys if k in self.hosts]
        return sorted({h for k in keys for h in self.hosts[k]}) if keys else None

    def is_approved(self, tool: str, keys: Iterable[str], code: str) -> bool:
        """Keyless tools need no approval. Otherwise the user approved this tool for these keys, and
        either this exact code or, while the guard fences the keys in no wider than when they
        approved, any rewrite of it: a rewrite then cannot do more with the keys than the original."""
        keys = set(keys)
        if self.approvals is None or not keys:
            return True
        approval = self.approvals.get(tool)
        if not approval or not keys <= set(approval["keys"]):
            return False
        if approval["sha256"] == code_hash(code):
            return True
        hosts, approved = self.allowed_hosts(keys), approval.get("hosts")
        return self.guard and hosts is not None and approved is not None and set(hosts) <= set(approved)

    def env_for(self, code: str, overrides: dict[str, str] | None = None, *, tool: str | None = None) -> dict[str, str]:
        """Process environment for a tool: scrubbed parent env + overrides + only its declared vars,
        plus the guard's configuration. With ``tool``, refuses keys the user has not approved."""
        declared = required_env(code)
        if tool is not None and not self.is_approved(tool, declared, code):
            raise PermissionError(
                f"the user has not approved tool {tool!r} to use {', '.join(declared)}; "
                f"approve with `autotool tools approve {tool} {' '.join(declared)}`"
            )
        env = sandbox_env({**(overrides or {}), **self.grant(declared)}, drop=self._drop)
        if self.guard:
            env["AUTOTOOL_GUARD"] = json.dumps({"hosts": self.allowed_hosts(declared), "protect": self.protect})
        return env

    def redact(self, text: str | None) -> str | None:
        if not text:
            return text
        for pattern, name in self._secrets:
            text = pattern.sub(f"[REDACTED:{name}]", text)
        return text

    def redact_json(self, obj: Any) -> Any:
        """``obj`` with secret values redacted inside every string, e.g. a tool schema whose
        parameter default was read from the environment."""
        return json.loads(self.redact(json.dumps(obj)))

    def leaked(self, text: str) -> list[str]:
        """Names of secrets whose value appears in ``text`` in any encoding ``redact`` handles."""
        return [name for pattern, name in self._secrets if pattern.search(text)]
