"""User policy in ~/.autotool/policy.json: per-key host allowlists and per-tool consent.

    {"hosts": {"TAVILY_API_KEY": ["api.tavily.com"]},
     "approvals": {"tavily_tool": {"keys": ["TAVILY_API_KEY"], "sha256": "<hash of the approved code>",
                                   "hosts": ["api.tavily.com"]}}}

An approval covers one tool name, one set of keys and the hosts those keys were limited to when
the user approved. Rewrites stay approved while that fence holds (see ToolEnv.is_approved);
otherwise only the exact approved code (sha256) is. A policy file that exists but cannot be understood is an error, never "no policy"
(that would silently drop every allowlist)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def normalize_host(host: str) -> str:
    """`https://API.Example.com:443/x` -> `api.example.com`; IDN -> punycode; keeps `*.` wildcards."""
    host = host.strip()
    if "://" in host:
        host = urlsplit(host).hostname or ""
    host = host.split("/")[0]
    if host.count(":") == 1:  # host:port (an IPv6 literal has several colons)
        host = host.split(":")[0]
    host = host.lower().rstrip(".")
    wildcard, base = (True, host[2:]) if host.startswith("*.") else (False, host)
    try:
        base = base.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    return ("*." if wildcard else "") + base


def _invalid(home: Path, why: str) -> ValueError:
    return ValueError(f"{home / 'policy.json'} is invalid ({why}); fix it, or delete it to start over")


def _retry_windows_sharing(action: Any) -> Any:
    """Windows briefly refuses to read or replace a file another process (a second AutoTool, the
    CLI, an antivirus scan) has open. Retry for up to ~5 s instead of failing the request."""
    for attempt in range(250):
        try:
            return action()
        except PermissionError:
            if attempt == 249:
                raise
            time.sleep(0.02)


def load_policy(home: Path) -> dict[str, Any]:
    path = home / "policy.json"
    try:
        policy = json.loads(_retry_windows_sharing(lambda: path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {"hosts": {}, "approvals": {}}
    except json.JSONDecodeError as exc:
        raise _invalid(home, f"not JSON: {exc.msg}") from None
    if not isinstance(policy, dict):
        raise _invalid(home, "not an object")
    policy.setdefault("hosts", {})
    policy.setdefault("approvals", {})
    hosts, approvals = policy["hosts"], policy["approvals"]
    if not isinstance(hosts, dict) or not all(isinstance(v, list) and all(isinstance(h, str) for h in v) for v in hosts.values()):
        raise _invalid(home, '"hosts" must map key names to lists of hosts')
    if not isinstance(approvals, dict) or not all(
        isinstance(a, dict)
        and isinstance(a.get("keys"), list)
        and isinstance(a.get("sha256"), str)
        and (a.get("hosts") is None or isinstance(a["hosts"], list))
        for a in approvals.values()
    ):
        raise _invalid(home, '"approvals" must map tool names to {"keys": [...], "sha256": "..."}')
    return policy


@contextlib.contextmanager
def _locked(home: Path) -> Iterator[None]:
    """Cross-process lock around read-modify-write: two servers and the CLI may update at once."""
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "policy.lock"
    deadline = time.monotonic() + 10
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):  # Windows: PermissionError while the holder deletes it
            try:
                if time.time() - lock.stat().st_mtime > 30:  # left behind by a crashed process
                    lock.unlink(missing_ok=True)
                    continue
            except (FileNotFoundError, PermissionError):
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock} is held by another process; delete it if no autotool is running") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _save(home: Path, policy: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=home, prefix=".policy-", suffix=".tmp")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, sort_keys=True)
    _retry_windows_sharing(lambda: os.replace(tmp, home / "policy.json"))


def _update(home: Path, change: Any) -> None:
    with _locked(home):
        policy = load_policy(home)
        change(policy)
        _save(home, policy)


def set_hosts(home: Path, name: str, hosts: Iterable[str]) -> list[str]:
    """Restrict tools holding ``name`` to these hosts; an empty list removes the restriction."""
    normalized = sorted({normalize_host(h) for h in hosts if h.strip()})

    def change(policy: dict[str, Any]) -> None:
        if normalized:
            policy["hosts"][name] = normalized
        else:
            policy["hosts"].pop(name, None)

    _update(home, change)
    return normalized


def approve(home: Path, tool: str, keys: Iterable[str], code: str, hosts: Iterable[str] | None = None) -> None:
    """``hosts``: where the keys were limited to when the user approved (None: unrestricted)."""
    approval = {"keys": sorted(set(keys)), "sha256": code_hash(code), "hosts": sorted(hosts) if hosts is not None else None}
    _update(home, lambda policy: policy["approvals"].__setitem__(tool, approval))


def revoke(home: Path, tool: str) -> None:
    _update(home, lambda policy: policy["approvals"].pop(tool, None))
