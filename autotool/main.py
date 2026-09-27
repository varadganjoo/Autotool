"""CLI entrypoint: ``python -m autotool.main "your objective"``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from dotenv import find_dotenv, load_dotenv

from autotool.core.llm import LLMProvider, default_provider
from autotool.core.orchestrator import Orchestrator, RunEvent, RunResult
from autotool.core.registry import ToolRegistry
from autotool.core.toolenv import ToolEnv
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
    tool_env: ToolEnv | None = None,
    verbose: bool = True,
) -> RunResult:
    tool_env = tool_env if tool_env is not None else ToolEnv.from_dotenv()
    verifier = ToolVerifier(staging_dir, timeout_s=timeout_s, env_overrides=env_overrides, tool_env=tool_env)
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=verifier, max_retries=max_retries)
    async with ToolRegistry(tools_dir, env_overrides=env_overrides, tool_env=tool_env) as registry:
        cached = await registry.load_cached()
        if verbose:
            print(f"Tool credentials from .env: {tool_env.names or 'none'}", file=sys.stderr)
            print(f"Mounted {len(cached)} cached tool server(s): {cached or 'none'}", file=sys.stderr)
        orchestrator = Orchestrator(provider, registry, engine, on_event=print_event if verbose else None)
        return await orchestrator.run(prompt)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autotool", description="Self-synthesizing MCP agent runtime")
    parser.add_argument("prompt", help="Objective for the agent")
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default=None,
        help="LLM backend (default: $AUTOTOOL_PROVIDER, else openai if OPENAI_API_KEY is set, else anthropic)",
    )
    parser.add_argument("--model", default=None, help="Model id (default: $AUTOTOOL_OPENAI_MODEL / $AUTOTOOL_MODEL)")
    parser.add_argument("--reasoning-effort", default=None, help="OpenAI reasoning effort, e.g. low|medium|high")
    parser.add_argument("--tools-dir", default="tools")
    parser.add_argument("--staging-dir", default=".staging")
    parser.add_argument("--timeout", type=float, default=15.0, help="Verification timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--no-fallbacks", action="store_true", help="Anthropic only: disable server-side refusal fallbacks")
    parser.add_argument(
        "--env-file", default=None, help="dotenv file whose variables synthesized tools may use (default: nearest .env)"
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))  # the demo agent's own model key (nearest .env)

    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
    try:
        provider = default_provider(
            args.provider, args.model, reasoning_effort=args.reasoning_effort, use_fallbacks=not args.no_fallbacks
        )
    except ImportError as exc:
        print(f"The demo agent needs a model SDK ({exc}). Install it with: pip install 'autotool-mcp[models]'", file=sys.stderr)
        return 2
    result = asyncio.run(
        run_objective(
            args.prompt,
            provider=provider,
            tools_dir=args.tools_dir,
            staging_dir=args.staging_dir,
            timeout_s=args.timeout,
            max_retries=args.max_retries,
            tool_env=ToolEnv.from_dotenv(args.env_file),
            verbose=not args.quiet,
        )
    )
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
