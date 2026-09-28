"""`autotool` command line: serve, setup, keys, tools, run."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys

import keyring.errors

from autotool import __version__
from autotool.core.credentials import autotool_home, keychain_delete, keychain_names, keychain_set, load_tool_env
from autotool.core.policy import approve, load_policy, revoke, set_hosts
from autotool.core.toolenv import RESERVED_PREFIXES, required_env


def sandbox_on(value: str) -> bool:
    """Fail safe: only an explicit off/0/false/no turns the guard off."""
    return value.strip().lower() not in {"off", "0", "false", "no"}


def consent_mode(value: str) -> str:
    """Fail safe: only the explicit "dangerously-allow-all" skips approvals."""
    return "auto" if value.strip().lower() == "dangerously-allow-all" else "prompt"


def _keys(args: argparse.Namespace) -> int:
    home = autotool_home()
    if args.action == "add":
        if args.name.upper().startswith(RESERVED_PREFIXES):
            print(
                f"{args.name} is reserved: names starting with {', '.join(RESERVED_PREFIXES)} configure AutoTool itself "
                "and are never given to tools. Store it under another name (e.g. MY_OPENAI_API_KEY).",
                file=sys.stderr,
            )
            return 1
        value = sys.stdin.readline().rstrip("\r\n") if args.stdin else getpass.getpass(f"Value for {args.name} (hidden): ")
        if not value:
            print("No value given; nothing stored.", file=sys.stderr)
            return 1
        try:
            keychain_set(home, args.name, value)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        except keyring.errors.KeyringError as exc:
            print(
                f"No OS keychain is available here ({exc}). Put the key in {home / '.env'} instead:\n  {args.name}=...",
                file=sys.stderr,
            )
            return 1
        print(f"Stored {args.name} in the OS keychain. Tools that declare it can use it; the model only sees the name.")
    elif args.action == "allow":
        hosts = set_hosts(home, args.name, args.hosts)
        print(f"{args.name}: tools holding it may only reach {', '.join(hosts)}." if hosts else f"{args.name}: no host limit.")
        if args.name not in load_tool_env(home).names:
            print(f"Note: no credential named {args.name} is set yet (names are case-sensitive).", file=sys.stderr)
    elif args.action == "remove":
        keychain_delete(home, args.name)
        print(f"Removed {args.name} from the keychain.")
    else:
        keychain = set(keychain_names(home))
        names = load_tool_env(home).names
        if not names:
            print(f"No credentials yet. Add one with `autotool keys add NAME` or in {home / '.env'}.")
        hosts = load_policy(home)["hosts"]
        for name in names:
            limit = f"hosts: {', '.join(hosts[name])}" if name in hosts else "any host"
            print(f"{name}  ({'keychain' if name in keychain else 'env'}; {limit})")
    return 0


def _tools(args: argparse.Namespace) -> int:
    tools_dir = autotool_home() / "tools"
    home = autotool_home()
    pending = home / ".staging" / "pending" / f"{args.name}.py"
    if args.action == "approve":
        # Approve exactly the code the agent submitted (pending) or, failing that, the cached tool.
        source = pending if pending.exists() else tools_dir / f"{args.name}.py"
        if not source.exists():
            print(f"No pending or cached tool named {args.name}; have your agent call create_tool first.", file=sys.stderr)
            return 1
        env = load_tool_env(home)
        approve(home, args.name, args.keys, source.read_text(encoding="utf-8"), env.allowed_hosts(args.keys))
        print(f"Approved {args.name} (this version of its code) to use {', '.join(args.keys)}.")
        return 0
    if args.action == "revoke":
        revoke(home, args.name)
        print(f"Revoked {args.name}'s approval; it will not get credentials until approved again.")
        return 0
    if args.action == "remove":
        path = tools_dir / f"{args.name}.py"
        if not path.exists():
            print(f"No tool named {args.name}.", file=sys.stderr)
            return 1
        path.unlink()
        pending.unlink(missing_ok=True)
        revoke(home, args.name)  # a new tool reusing the name must not inherit the approval
        print(f"Removed {args.name} and its approval. Hosts drop it on their next restart.")
        return 0
    scripts = sorted(p for p in tools_dir.glob("*.py") if not p.name.startswith("_")) if tools_dir.exists() else []
    if not scripts:
        print("No tools yet. Your agent creates them with the create_tool tool.")
    for p in scripts:
        try:
            creds = required_env(p.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            creds = ["<unreadable declaration>"]
        approved = load_tool_env(home, consent=True).is_approved(p.stem, creds, p.read_text(encoding="utf-8"))
        state = "" if not creds else (" (approved)" if approved else " (NOT approved)")
        print(f"{p.stem}  credentials: {', '.join(creds) or 'none'}{state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["run"]:  # the built-in demo agent keeps its own flags
        from autotool.main import cli

        return cli(argv[1:])

    parser = argparse.ArgumentParser(prog="autotool", description="A self-extending tool layer for any MCP agent.")
    parser.add_argument("--version", action="version", version=f"autotool-mcp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the MCP server (what your agent host launches).")
    serve.add_argument("--env-file", default=None, help="Extra dotenv file with tool credentials.")
    serve.add_argument("--log-level", default="WARNING")
    serve.add_argument(
        "--consent",
        default=os.environ.get("AUTOTOOL_CONSENT", "prompt"),
        help="'prompt' (default): ask before a tool first gets credentials. 'dangerously-allow-all': "
        "never ask. Same as --dangerously-allow-all-tools.",
    )
    serve.add_argument(
        "--dangerously-allow-all-tools",
        action="store_true",
        help="Skip approvals: every tool gets the credentials it declares without asking you. The guard "
        "and host allowlists still apply.",
    )
    serve.add_argument(
        "--sandbox",
        default=os.environ.get("AUTOTOOL_SANDBOX", "on"),
        help="Run tools under AutoTool's guard (default). Turn off if AutoTool already runs in a sandbox; "
        "host allowlists are then not enforced.",
    )

    setup = sub.add_parser("setup", help="Connect AutoTool to Claude Code, Codex, Claude Desktop, Cursor and OpenClaw.")
    setup.add_argument(
        "--hosts",
        nargs="*",
        default=None,
        choices=["claude-code", "codex", "claude-desktop", "cursor", "openclaw"],
        help="Limit to these hosts (default: every one detected).",
    )
    setup.add_argument("--dry-run", action="store_true", help="Show what would change without changing anything.")
    setup.add_argument(
        "--launcher",
        choices=["auto", "uvx", "python"],
        default="auto",
        help="How hosts start the server: installed `autotool` script, `uvx autotool-mcp`, or this Python.",
    )

    keys = sub.add_parser("keys", help="Manage credentials (OS keychain) and their host allowlists.")
    keys_sub = keys.add_subparsers(dest="action", required=True)
    add = keys_sub.add_parser("add", help="Store a credential (hidden prompt).")
    add.add_argument("name")
    add.add_argument("--stdin", action="store_true", help="Read the value from stdin instead of prompting.")
    keys_sub.add_parser("list", help="List credential names (never values) and their host allowlists.")
    allow = keys_sub.add_parser("allow", help="Limit tools holding a key to these hosts (wildcards like *.example.com).")
    allow.add_argument("name")
    allow.add_argument("hosts", nargs="*", help="Hosts; give none to remove the limit.")
    rm = keys_sub.add_parser("remove")
    rm.add_argument("name")

    tools = sub.add_parser("tools", help="List, approve, revoke or remove created tools.")
    tools_sub = tools.add_subparsers(dest="action", required=True)
    tools_sub.add_parser("list")
    trm = tools_sub.add_parser("remove")
    trm.add_argument("name")
    tap = tools_sub.add_parser("approve", help="Let a tool use these credentials.")
    tap.add_argument("name")
    tap.add_argument("keys", nargs="+")
    trv = tools_sub.add_parser("revoke", help="Withdraw a tool's approval.")
    trv.add_argument("name")

    sub.add_parser(
        "run",
        help='Demo agent: autotool run "objective". Needs autotool-mcp[models] and a key in ./.env; '
        "it has no consent prompts or allowlists and uses ./tools.",
    )

    args = parser.parse_args(argv)
    if args.command == "serve":
        logging.basicConfig(level=args.log_level.upper(), stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
        from autotool.server import serve as run_server

        consent = "auto" if args.dangerously_allow_all_tools else consent_mode(args.consent)
        asyncio.run(run_server(args.env_file, consent=consent, sandbox=sandbox_on(args.sandbox)))
        return 0
    if args.command == "setup":
        from autotool.setup import run_setup

        return run_setup(hosts=args.hosts, dry_run=args.dry_run, launcher=args.launcher)
    if args.command == "keys":
        return _keys(args)
    return _tools(args)


if __name__ == "__main__":
    raise SystemExit(main())
