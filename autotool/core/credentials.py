"""Where tool credentials come from when AutoTool runs as a user-hosted MCP server.

Highest precedence first:
1. the host's MCP config: ``AUTOTOOL_KEY_<NAME>=value`` is offered to tools as ``<NAME>``
   (the prefix makes sharing opt-in; hosts pass their whole environment to the server);
2. the OS keychain (``autotool keys add NAME``), names indexed in ``~/.autotool/keys.json``;
3. ``~/.autotool/.env``;
4. an explicit ``--env-file``.

The host project's own ``.env`` is never read implicitly."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Mapping

import keyring
from keyring.errors import KeyringError, PasswordDeleteError
from dotenv import dotenv_values

from autotool.core.policy import load_policy
from autotool.core.toolenv import ToolEnv, runtime_dotenv_names, runtime_dotenv_path

log = logging.getLogger(__name__)

HOME_ENV = "AUTOTOOL_HOME"
KEY_PREFIX = "AUTOTOOL_KEY_"
KEYRING_SERVICE = "autotool-mcp"
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def autotool_home() -> Path:
    return Path(os.environ.get(HOME_ENV) or Path.home() / ".autotool")


def _index(home: Path) -> Path:
    return home / "keys.json"


def keychain_names(home: Path) -> list[str]:
    try:
        return sorted(json.loads(_index(home).read_text(encoding="utf-8")))
    except FileNotFoundError:
        return []


def _write_index(home: Path, names: set[str]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    _index(home).write_text(json.dumps(sorted(names)), encoding="utf-8")


def keychain_set(home: Path, name: str, value: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"{name!r} is not a valid environment variable name (letters, digits, _; not starting with a digit)")
    keyring.set_password(KEYRING_SERVICE, name, value)
    _write_index(home, set(keychain_names(home)) | {name})


def keychain_delete(home: Path, name: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except PasswordDeleteError:
        pass
    _write_index(home, set(keychain_names(home)) - {name})


def load_tool_env(
    home: Path | None = None,
    env_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    consent: bool = False,
    guard: bool = True,
) -> ToolEnv:
    """``consent``: tools need the user's approval (policy.json) before receiving keys.
    ``guard``: run tools under autotool.guard, which also enforces per-key host allowlists."""
    home = home or autotool_home()
    environ = os.environ if environ is None else environ
    values: dict[str, str | None] = {}
    if env_file is not None:
        if not Path(env_file).is_file():
            raise FileNotFoundError(f"env file not found: {env_file}")
        values.update(dotenv_values(env_file))
    if (home / ".env").is_file():
        values.update(dotenv_values(home / ".env"))
    for name in keychain_names(home):
        try:
            values[name] = keyring.get_password(KEYRING_SERVICE, name)
        except KeyringError as exc:  # e.g. headless Linux with no keychain backend
            log.warning("Skipping %s: the OS keychain is unavailable (%s); put it in %s instead", name, exc, home / ".env")
    prefixed = [k for k in environ if k.upper().startswith(KEY_PREFIX)]
    values.update({k[len(KEY_PREFIX):]: environ[k] for k in prefixed})
    # Strip from tool processes: every source name (via ToolEnv), the prefixed originals, and the
    # .env llm.py loads into the server's own environment.
    policy = load_policy(home)
    from autotool.setup import host_config_paths  # host configs may hold AUTOTOOL_KEY_* values

    protect = [home / ".env", home / "keys.json", home / "policy.json", *([env_file] if env_file else []),
               *([runtime_dotenv_path()] if runtime_dotenv_path() else []), *host_config_paths()]
    return ToolEnv(values, also_drop=[*prefixed, *runtime_dotenv_names()], hosts=policy["hosts"],
                   approvals=policy["approvals"] if consent else None, protect=[str(p) for p in protect], guard=guard)
