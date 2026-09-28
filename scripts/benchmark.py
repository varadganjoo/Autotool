"""Benchmark AutoTool on tasks that need live public APIs.

For every task and trial it measures three conditions:
  cold      empty tools dir: the agent must synthesize, verify and hot-load a tool
  warm      same tools dir again: the cached tool is mounted at startup
  baseline  same model, no tools at all (can it answer without live data?)

Answers are graded against ground truth fetched directly from the same API at
grading time. Results go to results/benchmark-<timestamp>.json plus a Markdown
summary table.

    python scripts/benchmark.py --trials 3            # all tasks
    python scripts/benchmark.py --tasks hackernews pypi
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # model keys for the benchmark's own agents

from autotool.core.llm import default_provider  # noqa: E402
from autotool.main import run_objective  # noqa: E402


def _get(url: str) -> Any:
    r = httpx2.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "autotool-benchmark"})
    r.raise_for_status()
    return r.json()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text)]


# Each grader returns (passed, note). Ground truth is fetched at grading time.


def grade_hackernews(answer: str) -> tuple[bool, str]:
    base = "https://hacker-news.firebaseio.com/v0"
    ids = _get(f"{base}/topstories.json")[:5]  # allow for rank drift during the run
    titles = [(_get(f"{base}/item/{i}.json") or {}).get("title", "") for i in ids]
    hits = sum(1 for t in titles if t and _norm(t) in _norm(answer))
    return hits >= 2, f"{hits} of the current top-5 titles appear in the answer"


def grade_pypi(answer: str) -> tuple[bool, str]:
    version = _get("https://pypi.org/pypi/httpx2/json")["info"]["version"]
    return version in answer, f"expected httpx2 {version}"


def grade_npm(answer: str) -> tuple[bool, str]:
    version = _get("https://registry.npmjs.org/react/latest")["version"]
    return version in answer, f"expected react {version}"


def grade_countries(answer: str) -> tuple[bool, str]:
    data = _get("https://restcountries.com/v3.1/name/japan?fields=capital,population")[0]
    pop = data["population"]
    ok = "tokyo" in answer.lower() and any(abs(n - pop) / pop < 0.02 or abs(n * 1e6 - pop) / pop < 0.02 for n in _numbers(answer))
    return ok, f"expected Tokyo, population {pop:,}"


def grade_github(answer: str) -> tuple[bool, str]:
    stars = _get("https://api.github.com/repos/python/cpython")["stargazers_count"]
    candidates = _numbers(answer) + [n * 1000 for n in _numbers(answer)]  # accept "71.2k"
    ok = any(abs(n - stars) / stars < 0.02 for n in candidates)
    return ok, f"expected ~{stars:,} stars"


def grade_weather(answer: str) -> tuple[bool, str]:
    cur = _get("https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&current=temperature_2m")
    t = cur["current"]["temperature_2m"]
    ok = any(abs(n - abs(t)) <= 2.0 for n in _numbers(answer))
    return ok, f"expected ~{t} °C (±2)"


@dataclass
class Task:
    key: str
    prompt: str
    hosts: list[str]
    grade: Callable[[str], tuple[bool, str]]


TASKS = [
    Task(
        "hackernews",
        "Fetch the current top 3 stories from Hacker News using their public API and return the titles and URLs.",
        ["hacker-news.firebaseio.com"],
        grade_hackernews,
    ),
    Task(
        "pypi", "What is the latest released version of the Python package 'httpx2' on PyPI right now?", ["pypi.org"], grade_pypi
    ),
    Task(
        "npm",
        "What is the latest published version of the 'react' package on the npm registry?",
        ["registry.npmjs.org"],
        grade_npm,
    ),
    Task(
        "countries",
        "Using the REST Countries API, what is the capital of Japan and its population?",
        ["restcountries.com"],
        grade_countries,
    ),
    Task("github", "How many GitHub stars does the python/cpython repository have right now?", ["api.github.com"], grade_github),
    Task(
        "weather",
        "What is the current air temperature in Berlin (lat 52.52, lon 13.41) according to Open-Meteo?",
        ["api.open-meteo.com"],
        grade_weather,
    ),
]


def reachable(host: str) -> bool:
    try:
        httpx2.get(f"https://{host}/", timeout=8)
        return True
    except Exception:
        return False


async def run_condition(task: Task, condition: str, tools_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    provider = default_provider(args.provider, args.model)
    started = time.monotonic()
    row: dict[str, Any] = {"task": task.key, "condition": condition, "model": provider.model}
    try:
        if condition == "baseline":
            turn = await provider.complete(
                system="Answer the user's question as accurately as you can.",
                messages=[{"role": "user", "content": task.prompt}],
                tools=[],
            )
            answer, synth = turn.text, {}
            row.update(steps=1, synthesized=[])
        else:
            result = await run_objective(task.prompt, provider=provider, tools_dir=str(tools_dir), verbose=args.verbose)
            answer = result.answer
            synth = next((e.detail for e in result.events if e.kind == "synthesis"), {})
            row.update(
                steps=result.steps,
                synthesized=result.synthesized,
                tool_calls=[e.detail["name"] for e in result.events if e.kind == "tool_call"],
                tool_errors=sum(1 for e in result.events if e.kind == "tool_result" and e.detail["is_error"]),
            )
        row.update(
            synthesis_ok=synth.get("ok"),
            synthesis_attempts=synth.get("attempts"),
            synthesis_s=round(synth.get("elapsed_s", 0.0), 2) if synth else None,
            synthesis_error=(synth.get("error") or "")[:500] or None,
        )
        passed, note = task.grade(answer)
        row.update(answer=answer, passed=passed, grade_note=note, error=None)
    except Exception as exc:
        row.update(answer=None, passed=False, grade_note=None, error=f"{type(exc).__name__}: {exc}"[:800])
    row.update(
        wall_s=round(time.monotonic() - started, 2),
        llm_calls=provider.usage.calls,
        input_tokens=provider.usage.input_tokens,
        output_tokens=provider.usage.output_tokens,
    )
    return row


def summarize(rows: list[dict[str, Any]]) -> str:
    def mean(xs: list[float]) -> str:
        xs = [x for x in xs if x is not None]
        return f"{sum(xs) / len(xs):.1f}" if xs else "-"

    lines = [
        "| task | condition | pass | mean wall s | mean LLM calls | mean tokens (in/out) | mean synth attempts |",
        "|---|---|---|---|---|---|---|",
    ]
    keys = sorted({(r["task"], r["condition"]) for r in rows}, key=lambda k: (k[0], ["cold", "warm", "baseline"].index(k[1])))
    for task, cond in keys:
        rs = [r for r in rows if r["task"] == task and r["condition"] == cond]
        lines.append(
            f"| {task} | {cond} | {sum(r['passed'] for r in rs)}/{len(rs)} | {mean([r['wall_s'] for r in rs])} | "
            f"{mean([r['llm_calls'] for r in rs])} | {mean([r['input_tokens'] for r in rs])}/{mean([r['output_tokens'] for r in rs])} | "
            f"{mean([r.get('synthesis_attempts') for r in rs if cond == 'cold'])} |"
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="*", default=[t.key for t in TASKS])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--conditions", nargs="*", default=["cold", "warm", "baseline"])
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default=str(ROOT / "results"))
    parser.add_argument("--keep-tools", action="store_true", help="Keep synthesized tools under results/tools-*")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    tasks = [t for t in TASKS if t.key in args.tasks]
    probe = default_provider(args.provider, args.model)
    llm_host = httpx2.URL(str(probe.client.base_url)).host
    if not reachable(llm_host):
        print(f"LLM endpoint {llm_host} is unreachable from this environment; aborting.", file=sys.stderr)
        return 2
    print(f"provider={type(probe).__name__} model={probe.model} endpoint={llm_host}", file=sys.stderr)
    rows: list[dict[str, Any]] = []
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    for task in tasks:
        blocked = [h for h in task.hosts if not reachable(h)]
        if blocked:
            print(f"[skip] {task.key}: host(s) unreachable from this environment: {blocked}", file=sys.stderr)
            continue
        for trial in range(1, args.trials + 1):
            tools_dir = Path(tempfile.mkdtemp(prefix=f"autotool-{task.key}-"))
            try:
                for cond in args.conditions:
                    row = await run_condition(task, cond, tools_dir, args)
                    row["trial"] = trial
                    rows.append(row)
                    status = "PASS" if row["passed"] else "FAIL"
                    print(
                        f"[{task.key} #{trial} {cond}] {status} {row['wall_s']}s "
                        f"calls={row['llm_calls']} attempts={row.get('synthesis_attempts')} "
                        f"{row.get('error') or row.get('grade_note')}",
                        file=sys.stderr,
                    )
                if args.keep_tools:
                    shutil.copytree(tools_dir, out / f"tools-{stamp}" / f"{task.key}-{trial}", dirs_exist_ok=True)
            finally:
                shutil.rmtree(tools_dir, ignore_errors=True)
        (out / f"benchmark-{stamp}.json").write_text(json.dumps(rows, indent=2))

    table = summarize(rows) if rows else "(no results)"
    (out / f"benchmark-{stamp}.md").write_text(table + "\n")
    print("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
