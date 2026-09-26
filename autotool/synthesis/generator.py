"""LLM prompt pipeline that writes standalone FastMCP server scripts."""

from __future__ import annotations

import re

from autotool.core.llm import LLMProvider
from autotool.core.schema import CapabilityRequest, GeneratedToolCandidate, VerificationReport

GENERATOR_SYSTEM = """You write production-quality Model Context Protocol (MCP) tool servers in Python.

Every script you write MUST follow this contract:
- It is one self-contained file that runs as `python <file>.py` and serves MCP over stdio.
- It uses `from mcp.server.fastmcp import FastMCP` and creates `mcp = FastMCP("<tool_name>")`.
- Every tool is a function decorated with `@mcp.tool()` with full type annotations and a docstring
  that explains what it does and each parameter. Prefer simple parameter types (str, int, float, bool)
  with sensible defaults. Return a `str` (plain text or `json.dumps(...)` of the result).
- The file ends with:
      if __name__ == "__main__":
          mcp.run()
- Only import the standard library, `httpx`, `pydantic` and `mcp`.
- Use `httpx` with an explicit timeout of at most 10 seconds for network calls. Only use public,
  keyless APIs; never require or read API keys, tokens or other secrets.
- Make every external API base URL overridable through an environment variable named
  `<SERVICE>_API_BASE` (e.g. `HN_API_BASE`), defaulting to the real public URL.
- Let errors raise (e.g. `response.raise_for_status()`); FastMCP turns exceptions into tool errors,
  which is how the verification harness detects broken tools. Do not swallow exceptions.
- NEVER write to stdout (no bare `print`): stdout carries the MCP protocol. Log to stderr if needed.
- No subprocesses, no filesystem writes, no `eval`/`exec`.
- Keep the tool fast: bound fan-out (e.g. concurrent requests for at most ~30 items).

Also choose the primary tool and safe, realistic smoke-test arguments that exercise it cheaply
(e.g. a small limit)."""

TEMPLATE = '''import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example_tool")
API_BASE = os.environ.get("EXAMPLE_API_BASE", "https://api.example.com")


@mcp.tool()
def get_thing(thing_id: int, verbose: bool = False) -> str:
    """Fetch a thing by id.

    Args:
        thing_id: Numeric id of the thing.
        verbose: Include extra fields.
    """
    with httpx.Client(timeout=10) as client:
        resp = client.get(f"{API_BASE}/things/{thing_id}")
        resp.raise_for_status()
        return resp.text


if __name__ == "__main__":
    mcp.run()
'''

_FENCE_RE = re.compile(r"^```(?:python|py)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def clean_code(code: str) -> str:
    """Strip Markdown fences if the model wrapped the script in them."""
    code = code.strip()
    m = _FENCE_RE.match(code)
    return (m.group(1) if m else code).strip() + "\n"


class ToolGenerator:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    async def generate(self, request: CapabilityRequest) -> GeneratedToolCandidate:
        prompt = (
            f"Write the MCP server `{request.tool_name}` (use exactly `FastMCP(\"{request.tool_name}\")`).\n\n"
            f"Capability it must provide:\n{request.capability_description}\n\n"
            f"Structural reference (adapt, do not copy the example API):\n```python\n{TEMPLATE}```"
        )
        return self._finalize(await self.provider.structured(system=GENERATOR_SYSTEM, prompt=prompt, output_model=GeneratedToolCandidate))

    async def repair(
        self,
        request: CapabilityRequest,
        previous: GeneratedToolCandidate,
        report: VerificationReport,
        attempt: int,
    ) -> GeneratedToolCandidate:
        prompt = (
            f"Your MCP server `{request.tool_name}` failed automated verification (repair attempt {attempt}).\n\n"
            f"Capability it must provide:\n{request.capability_description}\n\n"
            f"Previous code:\n```python\n{previous.code}```\n\n"
            f"Smoke test: primary_tool={report.smoke_tool or previous.primary_tool!r}, "
            f"arguments={report.smoke_arguments if report.smoke_arguments is not None else previous.smoke_test_arguments_json}\n\n"
            f"{report.failure_summary()}\n\n"
            "Diagnose the root cause from the traceback / stderr and return a corrected, complete script. "
            "Keep the same contract. If the smoke-test arguments were the problem, fix them too."
        )
        return self._finalize(await self.provider.structured(system=GENERATOR_SYSTEM, prompt=prompt, output_model=GeneratedToolCandidate))

    @staticmethod
    def _finalize(candidate: GeneratedToolCandidate) -> GeneratedToolCandidate:
        return candidate.model_copy(update={"code": clean_code(candidate.code)})
