"""End-to-end demo: start with zero tools, synthesize `hackernews_tool.py`,
verify it in a subprocess, hot-load it, and print the top 3 stories.

Modes:
  --mode live     A real LLM (OpenAI by default when OPENAI_API_KEY is set, or
                  Claude via --provider anthropic) writes the tool; it calls the real HN API.
  --mode offline  No API key / network needed. A *scripted* LLM replays a fixed
                  sequence (including one deliberately broken first draft to
                  exercise the repair loop) and the tool talks to a local
                  HN-compatible fixture server via HN_API_BASE. Everything else
                  (staging, subprocess verification, MCP stdio, hot-loading,
                  orchestration) is the real runtime.
  --mode auto     live if credentials and news.ycombinator API are reachable, else offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")  # model keys for the benchmark's own agents

from autotool.core.llm import ScriptedProvider, default_provider  # noqa: E402
from autotool.core.orchestrator import SYNTHESIZE_TOOL  # noqa: E402
from autotool.core.schema import GeneratedToolCandidate, LLMTurn, ToolCall  # noqa: E402
from autotool.main import run_objective  # noqa: E402

PROMPT = "Fetch the current top 3 stories from Hacker News using their public API and return the titles and URLs."
HN_API = "https://hacker-news.firebaseio.com/v0"

# ---------------------------------------------------------------- offline replay

FIXTURE_STORIES = {
    9001: {
        "id": 9001,
        "type": "story",
        "title": "[fixture] Example story one",
        "url": "https://example.com/one",
        "score": 300,
        "by": "fixture",
    },
    9002: {
        "id": 9002,
        "type": "story",
        "title": "[fixture] Example story two",
        "url": "https://example.com/two",
        "score": 200,
        "by": "fixture",
    },
    9003: {"id": 9003, "type": "story", "title": "[fixture] Ask HN: example without a URL", "score": 150, "by": "fixture"},
    9004: {
        "id": 9004,
        "type": "story",
        "title": "[fixture] Example story four",
        "url": "https://example.com/four",
        "score": 90,
        "by": "fixture",
    },
}


class _FixtureHN(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/v0/topstories.json":
            body: Any = list(FIXTURE_STORIES)
        elif self.path.startswith("/v0/item/") and self.path.endswith(".json"):
            body = FIXTURE_STORIES.get(int(self.path[len("/v0/item/") : -len(".json")]))
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


def start_fixture_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v0"


HN_TOOL_CODE = '''"""Hacker News MCP server (public Firebase API, no key required)."""
import asyncio
import json
import os

import httpx2
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("hackernews_tool")
HN_API_BASE = os.environ.get("HN_API_BASE", "https://hacker-news.firebaseio.com/v0").rstrip("/")


@mcp.tool()
async def get_top_stories(limit: int = 3) -> str:
    """Return the current top Hacker News stories as JSON.

    Args:
        limit: Number of stories to return (1-30).
    """
    limit = max(1, min(int(limit), 30))
    async with httpx2.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{HN_API_BASE}/{TOP_PATH}")
        resp.raise_for_status()
        ids = resp.json()[:limit]

        async def fetch(item_id: int) -> dict:
            r = await client.get(f"{HN_API_BASE}/item/{item_id}.json")
            r.raise_for_status()
            return r.json() or {}

        items = await asyncio.gather(*(fetch(i) for i in ids))
    stories = [
        {
            "rank": rank,
            "id": item.get("id"),
            "title": item.get("title"),
            "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('id')}",
            "score": item.get("score"),
            "by": item.get("by"),
        }
        for rank, item in enumerate(items, start=1)
    ]
    return json.dumps(stories, indent=2)


if __name__ == "__main__":
    mcp.run()
'''

# First draft has a wrong endpoint (404) so the verifier fails and the repair loop runs.
BROKEN_DRAFT = HN_TOOL_CODE.replace("{TOP_PATH}", "topstory.json")
FIXED_DRAFT = HN_TOOL_CODE.replace("{TOP_PATH}", "topstories.json")


def build_scripted_provider() -> ScriptedProvider:
    drafts = iter([BROKEN_DRAFT, FIXED_DRAFT])

    def structured(prompt: str, model: type) -> GeneratedToolCandidate:
        return GeneratedToolCandidate(code=next(drafts), primary_tool="get_top_stories", smoke_test_arguments_json='{"limit": 3}')

    def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMTurn:
        names = {t["name"] for t in tools}
        last = messages[-1]["content"]
        last_result = last[-1] if isinstance(last, list) else None
        hn_tool = "hackernews_tool__get_top_stories"

        if last_result is None and hn_tool not in names:
            return LLMTurn(
                text="I have no tool for Hacker News yet; building one.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name=SYNTHESIZE_TOOL,
                        arguments={
                            "tool_name": "hackernews_tool",
                            "capability_description": "Fetch the current top N Hacker News stories via the public Firebase API "
                            "(topstories.json then item/<id>.json) and return rank, title, url, score and author as JSON.",
                        },
                    )
                ],
            )
        if hn_tool in names and not any(
            isinstance(m["content"], list) and any(b.get("type") == "tool_use" and b.get("name") == hn_tool for b in m["content"])
            for m in messages
            if m["role"] == "assistant"
        ):
            return LLMTurn(tool_calls=[ToolCall(id="call_2", name=hn_tool, arguments={"limit": 3})])

        stories = json.loads(last_result["content"])
        lines = [f"{s['rank']}. {s['title']}\n   {s['url']}" for s in stories]
        return LLMTurn(text="Top 3 Hacker News stories:\n" + "\n".join(lines))

    return ScriptedProvider(chat=chat, structured=structured)


# ---------------------------------------------------------------- main


def live_available() -> bool:
    if not any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import httpx2

        httpx2.get(f"{HN_API}/maxitem.json", timeout=5).raise_for_status()
        return True
    except Exception:
        return False


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["auto", "live", "offline"], default="auto")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--tools-dir", default=str(ROOT / "tools"))
    parser.add_argument("--keep-cache", action="store_true", help="Do not delete an existing hackernews_tool.py first")
    args = parser.parse_args()

    mode = args.mode if args.mode != "auto" else ("live" if live_available() else "offline")
    tools_dir = Path(args.tools_dir)
    cached = tools_dir / "hackernews_tool.py"
    if cached.exists() and not args.keep_cache:
        cached.unlink()  # start from zero synthesized tools

    env_overrides: dict[str, str] = {}
    server = None
    if mode == "offline":
        server, base = start_fixture_server()
        env_overrides["HN_API_BASE"] = base
        provider: Any = build_scripted_provider()
        print(f"== OFFLINE REPLAY: scripted LLM + local HN fixture at {base} ==", file=sys.stderr)
    else:
        provider = default_provider(args.provider, args.model)
        print(f"== LIVE: {type(provider).__name__} ({provider.model}) + real Hacker News API ==", file=sys.stderr)

    try:
        result = await run_objective(PROMPT, provider=provider, tools_dir=str(tools_dir), env_overrides=env_overrides)
    finally:
        if server:
            server.shutdown()

    print(f"\nsynthesized: {result.synthesized}  steps: {result.steps}  cached at: {cached}", file=sys.stderr)
    print("\n" + result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
