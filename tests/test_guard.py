"""The in-process guard every tool runs under, and the per-key host policy it enforces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from autotool.core.policy import approve, code_hash, load_policy, revoke, set_hosts
from autotool.core.toolenv import ToolEnv
from autotool.guard import host_allowed

ROOT = Path(__file__).resolve().parents[1]


def run_guarded(tmp_path: Path, body: str, config: dict) -> subprocess.CompletedProcess:
    script = tmp_path / "probe.py"
    script.write_text(textwrap.dedent(body))
    env = {**os.environ, "AUTOTOOL_GUARD": json.dumps(config), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "autotool.guard", str(script)], capture_output=True, text=True, env=env, timeout=60
    )


def test_host_patterns():
    assert host_allowed("api.tavily.com", ["api.tavily.com"])
    assert host_allowed("eu.api.example.com", ["*.example.com"]) and not host_allowed("example.com", ["*.example.com"])
    assert not host_allowed("api.tavily.com.evil.io", ["api.tavily.com"])
    assert host_allowed("API.Tavily.com.", ["api.tavily.com"])


def test_restricted_tool_cannot_reach_other_hosts(tmp_path):
    r = run_guarded(
        tmp_path,
        """
        import socket
        try:
            socket.getaddrinfo("exfil.example.org", 443)
        except PermissionError as e:
            print("BLOCKED", e)
        socket.getaddrinfo("localhost", 80)
        print("LOCALHOST OK")
    """,
        {"hosts": ["localhost"]},
    )
    assert "BLOCKED" in r.stdout and "exfil.example.org" in r.stdout and "LOCALHOST OK" in r.stdout, r.stderr


def test_unrestricted_tool_resolves_freely(tmp_path):
    r = run_guarded(
        tmp_path,
        """
        import socket
        socket.getaddrinfo("localhost", 80)
        print("OK")
    """,
        {"hosts": None},
    )
    assert "OK" in r.stdout, r.stderr


# These escape attempts never execute: the guard must refuse them before they run.
@pytest.mark.parametrize(
    "code, what",
    [
        ("import subprocess; subprocess.run(['whoami'])", "subprocess"),
        ("import os; os.system('whoami')", "os.system"),  # deliberate: proves the shell sink is blocked
        ("import keyring", "keyring"),
        ("import ctypes; ctypes.CDLL('msvcrt' if __import__('sys').platform == 'win32' else 'libc.so.6')", "ctypes"),
    ],
)
def test_escape_hatches_are_blocked(tmp_path, code, what):
    r = run_guarded(tmp_path, code, {})
    assert r.returncode != 0 and "blocked by AutoTool" in r.stderr and what in r.stderr, r.stderr


def test_credential_files_are_unreadable_and_writes_stay_in_temp(tmp_path):
    secret = tmp_path / "home" / ".env"
    secret.parent.mkdir()
    secret.write_text("OPENAI_API_KEY=sk-x\n")
    inside_temp = Path(tempfile.gettempdir()) / "autotool-guard-test.txt"
    outside_temp = ROOT / "guard-must-not-write-this.txt"  # tmp_path itself lives inside the temp dir
    r = run_guarded(
        tmp_path,
        f"""
        for attempt in (lambda: open({str(secret)!r}).read(), lambda: open({str(outside_temp)!r}, 'w')):
            try:
                attempt()
            except PermissionError as e:
                print("BLOCKED", e)
        open({str(inside_temp)!r}, "w").write("ok")
        print("TEMP OK")
    """,
        {"protect": [str(secret)]},
    )
    written = outside_temp.exists()
    outside_temp.unlink(missing_ok=True)
    inside_temp.unlink(missing_ok=True)
    assert r.stdout.count("BLOCKED") == 2 and "TEMP OK" in r.stdout and not written, r.stderr


def test_mcp_tool_server_still_runs_under_the_guard(tmp_path):
    import anyio

    from autotool.clients.dynamic_client import DynamicMCPClient
    from tests.test_synthesis import GOOD

    script = tmp_path / "math_tool.py"
    script.write_text(GOOD)
    env = ToolEnv().env_for(GOOD)
    assert "AUTOTOOL_GUARD" in env  # the guard is on by default

    async def call():
        async with DynamicMCPClient(script, env=env) as client:
            return (await client.call_tool("add", {"a": 1, "b": 2})).content[0].text

    assert anyio.run(call) == "3"


def test_sandbox_can_be_turned_off_for_hosts_that_are_already_sandboxed():
    env = ToolEnv({"A_KEY": "a" * 20}, hosts={"A_KEY": ["a.example.com"]}, guard=False)
    assert "AUTOTOOL_GUARD" not in env.env_for('REQUIRED_ENV = ["A_KEY"]')


# ---------------------------------------------------------------- policy


def test_policy_hosts_and_approvals_round_trip(tmp_path):
    set_hosts(tmp_path, "TAVILY_API_KEY", ["api.tavily.com"])
    approve(tmp_path, "tavily_tool", ["TAVILY_API_KEY"], "print(1)\n")
    policy = load_policy(tmp_path)
    assert policy["hosts"] == {"TAVILY_API_KEY": ["api.tavily.com"]}
    assert policy["approvals"] == {"tavily_tool": {"keys": ["TAVILY_API_KEY"], "sha256": code_hash("print(1)\n"), "hosts": None}}
    set_hosts(tmp_path, "TAVILY_API_KEY", [])
    revoke(tmp_path, "tavily_tool")
    assert load_policy(tmp_path) == {"hosts": {}, "approvals": {}}


def test_corrupt_policy_fails_closed_with_a_clear_message(tmp_path):
    for bad in ("{ not json", "[]", '{"hosts": null}', '{"approvals": {"t": ["A_KEY"]}}'):
        (tmp_path / "policy.json").write_text(bad)
        with pytest.raises(ValueError, match=r"policy\.json"):
            load_policy(tmp_path)


def test_concurrent_policy_updates_are_not_lost(tmp_path):
    import threading

    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            approve(tmp_path, f"tool{i}_tool", ["K"], f"# {i}\n")
            load_policy(tmp_path)  # readers outside the lock must not fail either
        except BaseException as exc:  # surface thread failures instead of losing them
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(load_policy(tmp_path)["approvals"]) == 12


def test_allowlist_hosts_are_normalized():
    from autotool.core.policy import normalize_host

    assert normalize_host("https://API.Tavily.com:443/search") == "api.tavily.com"
    assert normalize_host("*.Example.com.") == "*.example.com"
    assert normalize_host("m\u00fcller.example") == "xn--mller-kva.example"


def test_toolenv_restricts_egress_to_the_union_of_restricted_keys():
    env = ToolEnv(
        {"A_KEY": "a" * 20, "B_KEY": "b" * 20, "C_KEY": "c" * 20}, hosts={"A_KEY": ["a.example.com"], "B_KEY": ["b.example.com"]}
    )
    assert env.allowed_hosts(["C_KEY"]) is None  # no allowlist: unrestricted (opt-in feature)
    assert env.allowed_hosts(["A_KEY", "C_KEY"]) == ["a.example.com"]  # a restricted key restricts the tool
    assert sorted(env.allowed_hosts(["A_KEY", "B_KEY"])) == ["a.example.com", "b.example.com"]
    guard = json.loads(env.env_for('REQUIRED_ENV = ["A_KEY"]')["AUTOTOOL_GUARD"])
    assert guard["hosts"] == ["a.example.com"]


def test_toolenv_consent_is_bound_to_the_exact_code():
    code = 'REQUIRED_ENV = ["A_KEY"]\n'
    env = ToolEnv({"A_KEY": "a" * 20}, approvals={"good_tool": {"keys": ["A_KEY"], "sha256": code_hash(code)}})
    assert env.is_approved("good_tool", ["A_KEY"], code) and env.is_approved("any_tool", [], "x = 1")
    assert not env.is_approved("good_tool", ["A_KEY"], code + "# changed\n")  # new code asks again
    assert not env.is_approved("other_tool", ["A_KEY"], code)
    with pytest.raises(PermissionError, match="autotool tools approve other_tool A_KEY"):
        env.env_for(code, tool="other_tool")
    assert ToolEnv({"A_KEY": "a" * 20}).is_approved("other_tool", ["A_KEY"], code)  # consent off: approvals=None


def test_restricted_async_tool_runs_under_the_guard(tmp_path):
    # asyncio's event loop wakes itself over a loopback socket pair (127.0.0.1 on Windows): a tool
    # restricted to a remote host must still start.
    import anyio

    from autotool.clients.dynamic_client import DynamicMCPClient
    from tests.test_synthesis import GOOD

    code = GOOD.replace("mcp = MCPServer", 'REQUIRED_ENV = ["A_KEY"]\nmcp = MCPServer')
    script = tmp_path / "math_tool.py"
    script.write_text(code)
    env = ToolEnv({"A_KEY": "a" * 20}, hosts={"A_KEY": ["a.example.com"]}).env_for(code)

    async def call():
        async with DynamicMCPClient(script, env=env) as client:
            return (await client.call_tool("add", {"a": 1, "b": 2})).content[0].text

    assert anyio.run(call) == "3"


def test_async_connection_to_an_ip_literal_is_checked(tmp_path):
    # An IP literal skips name resolution, so only the connect check can stop it. asyncio's Windows
    # proactor loop connects without raising the socket.connect audit event.
    r = run_guarded(
        tmp_path,
        """
        import asyncio

        async def main():
            try:
                await asyncio.wait_for(asyncio.open_connection("192.0.2.1", 80), 3)  # TEST-NET-1, never routed
            except PermissionError as e:
                print("BLOCKED", e)
            except (OSError, asyncio.TimeoutError) as e:
                print("NOT BLOCKED", type(e).__name__)

        asyncio.run(main())
    """,
        {"hosts": ["a.example.com"]},
    )
    assert "BLOCKED blocked by AutoTool's guard: network access to 192.0.2.1" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("module", ["win32cred", "win32ctypes", "cffi"])
def test_other_credential_store_modules_are_blocked(tmp_path, module):
    import importlib.util

    if importlib.util.find_spec(module) is None:
        pytest.skip(f"{module} is not installed here")
    r = run_guarded(tmp_path, f"import {module}", {})
    assert "blocked by AutoTool" in r.stderr and module in r.stderr, r.stderr


def test_file_changes_outside_temp_are_blocked(tmp_path):
    victim = ROOT / "guard-victim.txt"
    victim.write_text("keep me")
    scratch = Path(tempfile.gettempdir()) / "autotool-guard-scratch"
    try:
        r = run_guarded(
            tmp_path,
            f"""
            import os, shutil
            from pathlib import Path
            victim, scratch = Path({str(victim)!r}), Path({str(scratch)!r})
            attempts = {{
                "unlink": victim.unlink,
                "rename": lambda: os.rename(victim, victim.with_suffix(".moved")),
                "link": lambda: os.link(victim, scratch.with_suffix(".lnk")),
                "chmod": lambda: os.chmod(victim, 0o444),
                "truncate": lambda: os.truncate(victim, 0),
                "o_trunc": lambda: os.close(os.open(victim, os.O_RDONLY | os.O_TRUNC)),
                "mkdir": lambda: os.mkdir(victim.with_suffix(".d")),
            }}
            for name, attempt in attempts.items():
                try:
                    attempt()
                    print("ALLOWED", name)
                except PermissionError:
                    print("BLOCKED", name)
            scratch.mkdir(exist_ok=True); (scratch / "f").write_text("x"); shutil.rmtree(scratch)
            print("TEMP OK")
        """,
            {},
        )
        assert "ALLOWED" not in r.stdout and r.stdout.count("BLOCKED") == 7 and "TEMP OK" in r.stdout, r.stdout + r.stderr
        assert victim.read_text() == "keep me"
    finally:
        victim.unlink(missing_ok=True)


def test_protected_file_reached_through_a_symlink_is_still_protected(tmp_path):
    secret = tmp_path / "secret.env"
    secret.write_text("K=v\n")
    link = Path(tempfile.gettempdir()) / "autotool-guard-link.env"
    link.unlink(missing_ok=True)
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("symlinks need extra privileges here")
    try:
        r = run_guarded(tmp_path, f"print(open({str(link)!r}).read())", {"protect": [str(secret)]})
        assert "blocked by AutoTool" in r.stderr, r.stdout + r.stderr
    finally:
        link.unlink(missing_ok=True)


def test_every_resolver_and_udp_send_is_checked(tmp_path):
    r = run_guarded(
        tmp_path,
        """
        import socket
        checks = {
            "gethostbyname": lambda: socket.gethostbyname("exfil.example.org"),
            "gethostbyname_ex": lambda: socket.gethostbyname_ex("exfil.example.org"),
            "gethostbyaddr": lambda: socket.gethostbyaddr("192.0.2.1"),
            "sendto": lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"k", ("192.0.2.1", 53)),
        }
        if hasattr(socket.socket, "sendmsg"):
            checks["sendmsg"] = lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendmsg([b"k"], [], 0, ("192.0.2.1", 53))
        for name, check in checks.items():
            try:
                check()
                print("ALLOWED", name)
            except PermissionError:
                print("BLOCKED", name)
            except OSError:
                print("ALLOWED", name)
    """,
        {"hosts": ["a.example.com"]},
    )
    assert "ALLOWED" not in r.stdout and "BLOCKED gethostbyname" in r.stdout, r.stdout + r.stderr


def test_resolution_state_is_per_thread():
    import threading

    from autotool import guard

    assert isinstance(guard._state, threading.local)


def test_approval_survives_rewrites_only_while_the_key_is_fenced_in():
    v1, v2 = 'REQUIRED_ENV = ["A_KEY"]\n', 'REQUIRED_ENV = ["A_KEY"]\n# rewritten\n'
    approval = {"keys": ["A_KEY"], "sha256": code_hash(v1), "hosts": ["a.example.com"]}
    fenced = ToolEnv({"A_KEY": "a" * 20}, hosts={"A_KEY": ["a.example.com"]}, approvals={"t": approval})
    assert fenced.is_approved("t", ["A_KEY"], v2)  # same keys, same allowed hosts: no new prompt
    widened = ToolEnv({"A_KEY": "a" * 20}, hosts={"A_KEY": ["a.example.com", "b.example.com"]}, approvals={"t": approval})
    assert not widened.is_approved("t", ["A_KEY"], v2) and widened.is_approved("t", ["A_KEY"], v1)
    open_key = ToolEnv({"A_KEY": "a" * 20}, approvals={"t": {**approval, "hosts": None}})
    assert not open_key.is_approved("t", ["A_KEY"], v2)  # no allowlist: a rewrite could send it anywhere
    no_guard = ToolEnv({"A_KEY": "a" * 20}, hosts={"A_KEY": ["a.example.com"]}, approvals={"t": approval}, guard=False)
    assert not no_guard.is_approved("t", ["A_KEY"], v2)  # allowlist not enforced: back to exact code
    more_keys = ToolEnv({"A_KEY": "a" * 20, "B_KEY": "b" * 20}, hosts={"A_KEY": ["a.example.com"]}, approvals={"t": approval})
    assert not more_keys.is_approved("t", ["A_KEY", "B_KEY"], v2)
