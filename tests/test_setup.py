"""`autotool setup` against fake homes: never touches the real host configs."""

from __future__ import annotations

import json
import subprocess

import pytest

from autotool import setup


def test_json_hosts_get_an_entry_a_backup_and_stay_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    cursor = tmp_path / ".cursor" / "mcp.json"
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    assert setup.run_setup(hosts=["cursor"], launcher="uvx") == 0
    data = json.loads(cursor.read_text())
    assert data["mcpServers"]["autotool"] == {"command": "uvx", "args": ["autotool-mcp", "serve"]}
    assert data["mcpServers"]["other"] == {"command": "x"}  # existing servers kept
    assert json.loads((tmp_path / ".cursor" / "mcp.json.bak").read_text()) == {"mcpServers": {"other": {"command": "x"}}}

    assert setup.add_to_json_config(cursor, ["uvx", "autotool-mcp", "serve"], dry_run=False) == "already configured"


def test_invalid_json_config_is_left_alone(tmp_path):
    bad = tmp_path / "mcp.json"
    bad.write_text("{ not json")
    assert "not valid JSON" in setup.add_to_json_config(bad, ["autotool", "serve"], dry_run=False)
    assert bad.read_text() == "{ not json"


def test_claude_code_uses_its_cli_and_dry_run_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["mcp", "get"] else 0, "", "")  # not registered yet

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    setup.run_setup(hosts=["claude-code"], dry_run=True, launcher="uvx")
    assert all(c[1:3] == ["mcp", "get"] for c in calls)  # dry run only looks
    setup.run_setup(hosts=["claude-code"], launcher="uvx")
    assert calls[-1] == ["/bin/claude", "mcp", "add", "--scope", "user", "autotool", "--", "uvx", "autotool-mcp", "serve"]


def test_rerunning_setup_keeps_credentials_in_the_entry(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"autotool": {"command": "old", "args": ["serve"], "env": {"AUTOTOOL_KEY_X": "v"}}}}))
    setup.add_to_json_config(cfg, ["autotool", "serve"], dry_run=False)
    entry = json.loads(cfg.read_text())["mcpServers"]["autotool"]
    assert entry == {"command": "autotool", "args": ["serve"], "env": {"AUTOTOOL_KEY_X": "v"}}
    assert setup.add_to_json_config(cfg, ["autotool", "serve"], dry_run=False) == "already configured"


def test_unexpected_json_shapes_are_left_alone(tmp_path):
    cfg = tmp_path / "mcp.json"
    for content in ("[]", '{"mcpServers": null}'):
        cfg.write_text(content)
        assert "skipped" in setup.add_to_json_config(cfg, ["autotool", "serve"], dry_run=False)
        assert cfg.read_text() == content


def test_existing_claude_code_entry_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None)
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "autotool: ...", "")  # `mcp get` finds it

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    setup.run_setup(hosts=["claude-code"], launcher="uvx")
    assert [c[1:3] for c in calls] == [["mcp", "get"]]


@pytest.mark.parametrize("cache", [("AppData", "Local", "uv", "cache"), (".cache", "uv")])  # Windows, Linux/macOS
def test_setup_run_through_uvx_registers_uvx_not_its_cache_path(monkeypatch, tmp_path, cache):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup.sys, "executable", str(tmp_path.joinpath(*cache, "archive-v0", "abc", "bin", "python")))
    assert setup.launch_command("auto") == ["uvx", "autotool-mcp", "serve"]


def test_codex_is_registered_through_its_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/bin/codex" if name == "codex" else None)
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["mcp", "get"] else 0, "", "")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    setup.run_setup(hosts=["codex"], launcher="uvx")
    assert calls[-1] == ["/bin/codex", "mcp", "add", "autotool", "--", "uvx", "autotool-mcp", "serve"]


def test_setting_values_fail_safe():
    from autotool.cli import consent_mode, sandbox_on

    assert [sandbox_on(v) for v in ("on", "ON", "1", "true", "yes", "garbage", "")] == [True] * 7
    assert [sandbox_on(v) for v in ("off", "OFF", "0", "false", "No")] == [False] * 5
    assert [consent_mode(v) for v in ("dangerously-allow-all", " DANGEROUSLY-ALLOW-ALL ")] == ["auto"] * 2
    assert [consent_mode(v) for v in ("prompt", "auto", "off", "yes", "garbage", "")] == ["prompt"] * 6


def test_removing_a_tool_revokes_its_approval(tmp_path, monkeypatch):
    from autotool.cli import main
    from autotool.core.policy import approve, load_policy

    monkeypatch.setenv("AUTOTOOL_HOME", str(tmp_path))
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "t_tool.py").write_text("x = 1\n")
    approve(tmp_path, "t_tool", ["K"], "x = 1\n")
    assert main(["tools", "remove", "t_tool"]) == 0
    assert "t_tool" not in load_policy(tmp_path)["approvals"]
