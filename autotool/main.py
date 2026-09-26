"""CLI entrypoint: ``python -m autotool.main "your objective"``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from autotool.core.llm import DEFAULT_MODEL, AnthropicProvider, LLMProvider
from autotool.core.orchestrator import Orchestrator, RunEvent, RunResult
from autotool.core.registry import ToolRegistry
from autotool.synthesis.repair import SynthesisEngine
from autotool.synthesis.verifier import ToolVerifier


def print_event(event: RunEvent) -> None:
    d = event.detail
    if event.kind == "llm" and d.get("tool_calls"):
        print(f"[step {d['step']}] LLM requested: {', '.join(d['tool_calls'])}", file=sys.stderr)
    elif event.kind == "tool_call":
        print(f"  -> {d['name']}({d['arguments']})", file=sys.stderr)
    elif event.kind == "synthesis":
        status = "OK" if d.get("ok") else "FAILED"
        print(f"  [synthesis {status}] {d.get('tool_name')} attempts={d.get('attempts')} {d.get('path', d.get('error', ''))}", file=sys.stderr)
    elif event.kind == "tool_result":
        flag = "error" if d["is_error"] else "ok"
        preview = d["content"].replace("\n", " ")[:160]
        print(f"  <- {d['name']} [{flag}] {preview}", file=sys.stderr)


async def run_objective(
    prompt: str,
    *,
    provider: LLMProvider,
    tools_dir: str = "tools",
    staging_dir: str = ".staging",
    timeout_s: float = 15.0,
    max_retries: int = 3,
    env_overrides: dict[str, str] | None = None,
    verbose: bool = True,
) -> RunResult:
    verifier = ToolVerifier(staging_dir, timeout_s=timeout_s, env_overrides=env_overrides)
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=verifier, max_retries=max_retries)
    async with ToolRegistry(tools_dir, env_overrides=env_overrides) as registry:
        cached = await registry.load_cached()
        if verbose:
            print(f"Mounted {len(cached)} cached tool server(s): {cached or 'none'}", file=sys.stderr)
        orchestrator = Orchestrator(provider, registry, engine, on_event=print_event if verbose else None)
        return await orchestrator.run(prompt)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autotool", description="Self-synthesizing MCP agent runtime")
    parser.add_argument("prompt", help="Objective for the agent")
    parser.add_argument("--model", default=None, help=f"Claude model id (default: $AUTOTOOL_MODEL or {DEFAULT_MODEL})")
    parser.add_argument("--tools-dir", default="tools")
    parser.add_argument("--staging-dir", default=".staging")
    parser.add_argument("--timeout", type=float, default=15.0, help="Verification timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--no-fallbacks", action="store_true", help="Disable server-side refusal fallbacks")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
    provider = AnthropicProvider(args.model, use_fallbacks=not args.no_fallbacks)
    result = asyncio.run(
        run_objective(
            args.prompt,
            provider=provider,
            tools_dir=args.tools_dir,
            staging_dir=args.staging_dir,
            timeout_s=args.timeout,
            max_retries=args.max_retries,
            verbose=not args.quiet,
        )
    )
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
