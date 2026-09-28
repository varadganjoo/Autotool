"""`autotool setup`: register the AutoTool MCP server with the agent hosts on this machine."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from autotool.core.credentials import autotool_home

NAME = "autotool"


def launch_command(launcher: str = "auto") -> list[str]:
    exe = shutil.which("autotool") if launcher == "auto" else None
    # `uvx autotool-mcp setup` runs from uv's cache, which `uv cache clean` deletes: register uvx instead.
    parts = {p.lower() for p in Path(sys.executable).parts}
    in_uv_cache = "uv" in parts and bool(parts & {"cache", ".cache"})  # %LOCALAPPDATA%\uv\cache, ~/.cache/uv
    if launcher == "uvx" or (launcher == "auto" and not exe and in_uv_cache):
        return ["uvx", "autotool-mcp", "serve"]
    return [exe, "serve"] if exe else [sys.executable, "-m", "autotool", "serve"]


def claude_desktop_config() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def host_config_paths() -> list[Path]:
    """Every host config that may hold AutoTool's entry (and its AUTOTOOL_KEY_* values)."""
    home = Path.home()
    return [
        home / ".claude.json",
        home / ".codex" / "config.toml",
        home / ".cursor" / "mcp.json",
        claude_desktop_config(),
        home / ".openclaw" / "openclaw.json",
        home / ".openclaw" / "config.json",
    ]


def add_to_json_config(path: Path, cmd: list[str], dry_run: bool) -> str:
    """Add ``mcpServers.autotool`` to a Claude Desktop / Cursor style config, keeping a .bak."""
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return f"skipped: {path} is not valid JSON; add the server by hand"
    if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
        return f"skipped: {path} has an unexpected shape; add the server by hand"
    old = data["mcpServers"].get(NAME) or {}
    if (old.get("command"), old.get("args")) == (cmd[0], cmd[1:]):
        return "already configured"
    if dry_run:
        return f"would add to {path}"
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    data["mcpServers"][NAME] = {**old, "command": cmd[0], "args": cmd[1:]}  # keep env (AUTOTOOL_KEY_*) and the rest
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return f"added to {path} (restart the app)"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 1, "", f"`{' '.join(cmd[:3])}` did not answer within 3 minutes")


def _claude_code(exe: str, cmd: list[str], dry_run: bool) -> str:
    # Never remove-and-re-add: the existing entry may hold the user's AUTOTOOL_KEY_* credentials.
    if _run([exe, "mcp", "get", NAME]).returncode == 0:
        return f"already configured (to change it: claude mcp remove {NAME}, then re-run setup)"
    add = [exe, "mcp", "add", "--scope", "user", NAME, "--", *cmd]
    if dry_run:
        return "would run: " + " ".join(add)
    r = _run(add)
    return "added (user scope)" if r.returncode == 0 else f"failed: {(r.stderr or r.stdout).strip()[:200]}"


def _codex(exe: str, cmd: list[str], dry_run: bool) -> str:
    if _run([exe, "mcp", "get", NAME]).returncode == 0:  # keep an existing entry (and its env) as it is
        return f"already configured (to change it: codex mcp remove {NAME}, then re-run setup)"
    add = [exe, "mcp", "add", NAME, "--", *cmd]
    if dry_run:
        return "would run: " + " ".join(add)
    r = _run(add)
    return "added" if r.returncode == 0 else f"failed: {(r.stderr or r.stdout).strip()[:200]}"


def _openclaw(exe: str, cmd: list[str], dry_run: bool) -> str:
    snippet = json.dumps({"mcp": {"servers": {NAME: {"command": cmd[0], "args": cmd[1:]}}}})
    # OpenClaw's MCP CLI changed across releases; only drive it when `mcp set` takes --command.
    probe = _run([exe, "mcp", "set", "--help"])
    if probe.returncode != 0 or "--command" not in probe.stdout:
        return f"this OpenClaw has no `mcp set --command`; upgrade it, or add to its config: {snippet}"
    set_cmd = [exe, "mcp", "set", NAME, "--command", cmd[0], "--args", *cmd[1:]]
    if dry_run:
        return "would run: " + " ".join(set_cmd)
    r = _run(set_cmd)
    return "added" if r.returncode == 0 else f"failed: {(r.stderr or r.stdout).strip()[:200]}; add to its config: {snippet}"


def run_setup(hosts: list[str] | None = None, dry_run: bool = False, launcher: str = "auto") -> int:
    cmd = launch_command(launcher)
    home = Path.home()
    detected = {
        "claude-code": shutil.which("claude"),
        "codex": shutil.which("codex"),
        "claude-desktop": claude_desktop_config().parent.exists() or None,
        "cursor": shutil.which("cursor") or (home / ".cursor").exists() or None,
        "openclaw": shutil.which("openclaw"),
    }
    results = []
    for host, found in detected.items():
        if hosts is not None and host not in hosts:
            continue
        if not found:
            results.append((host, "not found"))
        elif host == "claude-code":
            results.append((host, _claude_code(found, cmd, dry_run)))
        elif host == "codex":
            results.append((host, _codex(found, cmd, dry_run)))
        elif host == "openclaw":
            results.append((host, _openclaw(found, cmd, dry_run)))
        else:
            path = claude_desktop_config() if host == "claude-desktop" else home / ".cursor" / "mcp.json"
            results.append((host, add_to_json_config(path, cmd, dry_run)))

    print(f"Server command: {' '.join(cmd)}")
    for host, status in results:
        print(f"  {host:15} {status}")
    print(
        f"\nAdd credentials with `autotool keys add NAME` or in {autotool_home() / '.env'}; "
        "your agent sees their names, never their values.\n"
        f"Your own agent: connect any MCP client to `{' '.join(cmd)}` over stdio."
    )
    return 0
