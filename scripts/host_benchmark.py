"""Benchmark AutoTool as an MCP server under real agent hosts.

Hosts
  claude-code  `claude -p` (headless) with only the AutoTool MCP server and no built-in tools,
               so every capability has to come through AutoTool.
  custom       examples/mcp_agent.py: a minimal agent of your own (OpenAI model) over MCP.

Both hosts write tool code themselves through create_tool (synthesize_tool is disabled). Each
run gets a fresh AUTOTOOL_HOME; credentials reach the server only as AUTOTOOL_KEY_* variables in
its MCP config. Everything the host's model saw (Claude Code's stream-json transcript; every
request of the custom agent), the final answer and the created tools are scanned for every
secret value. Results: results/hosts-<stamp>.json and .md.

    python scripts/host_benchmark.py --trials 3
    python scripts/host_benchmark.py --hosts custom --tasks nimbus_header --trials 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, find_dotenv
from mcp import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "examples")]

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # model keys for the benchmark's own agents

import auth_benchmark as ab  # noqa: E402

from autotool import run_agent  # noqa: E402
from autotool.core.llm import default_provider  # noqa: E402
from autotool.core.toolenv import ToolEnv, required_env  # noqa: E402

DEFAULT_TASKS = ["nimbus_header", "ledgerly_bearer", "quotient_query", "parcelly_basic", "websearch_news", "composio_github"]
SECRET_NAMES = set(dotenv_values(find_dotenv(usecwd=True)))  # the repo .env, which llm.py loads into os.environ
KEEP_ENV = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOME",
)


# Host allowlists for every credential in play: tools can only reach the service their key is for.
ALLOWLISTS = {
    "TAVILY_API_KEY": ["api.tavily.com"],
    "COMPOSIO_API_KEY": ["backend.composio.dev"],
    "UNUSED_SERVICE_TOKEN": ["unused.example"],
    **{k: ["127.0.0.1", "localhost"] for k in ab.MOCK if k != "UNUSED_SERVICE_TOKEN"},
}


def server_env(home: Path, creds: dict[str, str], consent: str = "dangerously-allow-all") -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    (home / "policy.json").write_text(json.dumps({"hosts": ALLOWLISTS, "approvals": {}}))
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update(
        {
            "AUTOTOOL_HOME": str(home),
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",  # no synthesize_tool
            "AUTOTOOL_CONSENT": consent,
        }
    )
    env.update({f"AUTOTOOL_KEY_{k}": v for k, v in creds.items()})
    return env


def run_claude_code(prompt: str, env: dict[str, str], workdir: Path, model: str | None) -> dict[str, Any]:
    cfg = workdir / "mcp.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"autotool": {"command": sys.executable, "args": ["-m", "autotool", "serve"], "env": env}}})
    )
    cmd = [
        shutil.which("claude"),
        "-p",
        prompt,
        "--mcp-config",
        str(cfg),
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        "mcp__autotool",
        "--output-format",
        "stream-json",
        "--verbose",
        "--settings",
        json.dumps({"disableAllHooks": True}),
    ]  # the user's own plugins must not steer the run
    if model:
        cmd += ["--model", model]
    # Headless -p no longer waits for stdio MCP servers (CLI >= 2.1.144); single-turn runs need it to.
    claude_env = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES} | {"MCP_CONNECTION_NONBLOCKING": "0"}
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=900, cwd=workdir, stdin=subprocess.DEVNULL, env=claude_env
    )
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
    calls = [
        c["name"].removeprefix("mcp__autotool__")
        for e in events
        if e.get("type") == "assistant"
        for c in e["message"].get("content", [])
        if c.get("type") == "tool_use"
    ]
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return {
        "answer": result.get("result") or "",
        "calls": calls,
        "transcript": proc.stdout,
        "cost_usd": result.get("total_cost_usd"),
        "error": None if result else (proc.stderr or proc.stdout)[-800:],
    }


def codex_exe() -> str:
    exe = shutil.which("codex") or "codex"
    if exe.lower().endswith(".cmd"):  # npm shim: cmd.exe would mangle the TOML overrides, use the native binary
        found = sorted(Path(exe).parent.glob("node_modules/@openai/codex/node_modules/@openai/codex-*/vendor/*/bin/codex.exe"))
        exe = str(found[0]) if found else exe
    return exe


def run_codex(prompt: str, env: dict[str, str], workdir: Path, model: str | None) -> dict[str, Any]:
    toml_env = "{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in env.items()) + "}"
    # No shell, browser, apps, plugins, hooks or web search: every capability has to come through AutoTool.
    off = [
        "features.shell_tool=false",
        "features.apps=false",
        "features.browser_use=false",
        "features.computer_use=false",
        "features.plugins=false",
        "features.hooks=false",
        'web_search="disabled"',
    ]
    cmd = [
        codex_exe(),
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "-s",
        "read-only",
        *[a for o in off for a in ("-c", o)],
        "-c",
        f"mcp_servers.autotool.command={json.dumps(sys.executable)}",
        "-c",
        'mcp_servers.autotool.args=["-m","autotool","serve"]',
        "-c",
        f"mcp_servers.autotool.env={toml_env}",
        # exec runs with approval policy "never", which auto-rejects MCP calls unless the server is pre-approved.
        "-c",
        'mcp_servers.autotool.default_tools_approval_mode="approve"',
    ]
    if model:
        cmd += ["-m", model]
    codex_env = {k: v for k, v in os.environ.items() if k not in SECRET_NAMES}
    proc = subprocess.run(
        [*cmd, prompt],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
        cwd=workdir,
        stdin=subprocess.DEVNULL,
        env=codex_env,
    )
    items = [
        e["item"]
        for line in proc.stdout.splitlines()
        if line.startswith("{")
        for e in [json.loads(line)]
        if e.get("type") == "item.completed"
    ]
    calls = [i.get("tool", "") for i in items if i.get("type") == "mcp_tool_call"]
    answer = next((i["text"] for i in reversed(items) if i.get("type") == "agent_message"), "")
    usage = [json.loads(line)["usage"] for line in proc.stdout.splitlines() if line.startswith('{"type":"turn.completed"')]
    tokens = [sum(u.get("input_tokens", 0) for u in usage), sum(u.get("output_tokens", 0) for u in usage)]
    return {
        "answer": answer,
        "calls": calls,
        "transcript": proc.stdout,
        "cost_usd": None,
        "tokens": tokens,
        "error": None if answer else (proc.stderr or proc.stdout)[-800:],
    }


async def run_custom(prompt: str, env: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    provider = ab.RecordingProvider(default_provider(args.provider, args.model))
    calls: list[str] = []
    prompts: list[str] = []  # a simulated user who approves every consent prompt it is shown
    answer = await run_agent(
        prompt,
        provider,
        server=StdioServerParameters(command=sys.executable, args=["-m", "autotool", "serve"], env=env),
        on_tool=lambda name, a, r: calls.append(name),
        on_consent=lambda msg: prompts.append(msg) or True,
    )
    return {
        "answer": answer,
        "calls": calls,
        "transcript": "\n".join(provider.sent + prompts),
        "cost_usd": None,
        "error": None,
        "tokens": [provider.usage.input_tokens, provider.usage.output_tokens],
        "consent_prompts": prompts,
    }


async def run_one(
    host: str,
    task: ab.Task,
    creds: dict[str, str],
    detector: ToolEnv,
    args: argparse.Namespace,
    trial: int,
    out: Path,
    stamp: str,
) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix=f"autotool-host-{host}-{task.key}-"))
    home = work / "home"
    env = server_env(home, creds, consent="prompt" if host == "custom" else "dangerously-allow-all")
    started = time.monotonic()
    row: dict[str, Any] = {"host": host, "task": task.key, "suite": task.suite, "trial": trial, "expected_env": task.expected_env}
    try:
        if host == "claude-code":
            res = run_claude_code(task.prompt, env, work, args.claude_model)
        elif host == "codex":
            res = run_codex(task.prompt, env, work, args.codex_model)
        else:
            res = await run_custom(task.prompt, env, args)
    except Exception as exc:
        res = {"answer": "", "calls": [], "transcript": "", "cost_usd": None, "error": f"{type(exc).__name__}: {exc}"[:800]}
    code, declared = "", {}
    for p in sorted((home / "tools").glob("*.py")):
        code += p.read_text(encoding="utf-8")
        try:
            declared[p.stem] = required_env(p.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            declared[p.stem] = ["<invalid>"]
    if args.keep_tools:
        kept = out / f"hosts-tools-{stamp}" / f"{host}-{task.key}-{trial}"
        if (home / "tools").exists():
            shutil.copytree(home / "tools", kept, dirs_exist_ok=True)
        kept.mkdir(parents=True, exist_ok=True)
        (kept / "transcript.txt").write_text(detector.redact(res["transcript"]), encoding="utf-8")  # redacted, just in case
    shutil.rmtree(work, ignore_errors=True)

    passed, note = task.grade(res["answer"]) if res["answer"] else (False, None)
    calls = res["calls"]
    all_declared = {n for names in declared.values() for n in names}
    row.update(
        passed=passed,
        grade_note=note,
        answer=res["answer"],
        error=res["error"],
        calls=calls,
        create_calls=calls.count("create_tool"),
        native_calls=sum(1 for c in calls if "__" in c),
        run_tool_calls=calls.count("run_tool"),
        declared_env=declared,
        env_match=all_declared == set(task.expected_env),
        overprivileged=sorted(all_declared - set(task.expected_env)),
        leaks=detector.leaked(res["transcript"] + "\n" + res["answer"] + "\n" + code),
        redactions=res["transcript"].count("[REDACTED:"),
        guard_blocks=res["transcript"].count("blocked by AutoTool's guard"),
        consent_prompts=len(res.get("consent_prompts") or []),
        wall_s=round(time.monotonic() - started, 1),
        cost_usd=res.get("cost_usd"),
        tokens=res.get("tokens"),
    )
    return row


def summarize(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| host | task | pass | env match | leaks | create_tool calls | native / run_tool calls | mean wall s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for host, task in dict.fromkeys((r["host"], r["task"]) for r in rows):
        rs = [r for r in rows if r["host"] == host and r["task"] == task]
        lines.append(
            f"| {host} | {task} | {sum(r['passed'] for r in rs)}/{len(rs)} | {sum(r['env_match'] for r in rs)}/{len(rs)} | "
            f"{sum(len(r['leaks']) for r in rs)} | {sum(r['create_calls'] for r in rs) / len(rs):.1f} | "
            f"{sum(r['native_calls'] for r in rs)} / {sum(r['run_tool_calls'] for r in rs)} | {sum(r['wall_s'] for r in rs) / len(rs):.1f} |"
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hosts", nargs="*", default=["claude-code", "custom"])
    parser.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--provider", default=None, help="custom host's model provider")
    parser.add_argument("--model", default=None, help="custom host's model")
    parser.add_argument("--claude-model", default=None)
    parser.add_argument("--codex-model", default=None)
    parser.add_argument("--out", default=str(ROOT / "results"))
    parser.add_argument("--keep-tools", action="store_true")
    args = parser.parse_args()

    dot = {k: v for k, v in dotenv_values(find_dotenv(usecwd=True)).items() if v}
    creds = {**{k: v for k, v in dot.items() if k in ("TAVILY_API_KEY", "COMPOSIO_API_KEY")}, **ab.MOCK}
    detector = ToolEnv({**{f"SCAN_{k}": v for k, v in dot.items()}, **ab.MOCK})
    tasks = [t for t in ab.mock_tasks(ab.start_mock()) + ab.real_tasks(creds) if t.key in args.tasks]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows: list[dict[str, Any]] = []
    for host in args.hosts:
        for task in tasks:
            for trial in range(1, args.trials + 1):
                row = await run_one(host, task, creds, detector, args, trial, out, stamp)
                rows.append(row)
                print(
                    f"[{host} {task.key} #{trial}] {'PASS' if row['passed'] else 'FAIL'} {row['wall_s']}s calls={row['calls']} "
                    f"declared={row['declared_env']} leaks={row['leaks']} {row['error'] or row['grade_note']}",
                    file=sys.stderr,
                )
                (out / f"hosts-{stamp}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    table = summarize(rows) if rows else "(no results)"
    (out / f"hosts-{stamp}.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
