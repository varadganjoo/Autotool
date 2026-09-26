"""Offline tests for the synthesis pipeline, the hot-loader and the orchestrator.
No API key or network needed: LLM output is scripted, tools are pure compute."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from autotool.clients.dynamic_client import DynamicMCPClient, sandbox_env
from autotool.core.llm import ScriptedProvider
from autotool.core.orchestrator import SYNTHESIZE_TOOL, Orchestrator
from autotool.core.registry import ToolRegistry
from autotool.core.schema import CapabilityRequest, GeneratedToolCandidate, LLMTurn, ToolCall
from autotool.synthesis.generator import clean_code
from autotool.synthesis.repair import SynthesisEngine, SynthesisError
from autotool.synthesis.verifier import ToolVerifier, mock_arguments, static_check


def server(body: str, name: str = "math_tool") -> str:
    return (
        "from mcp.server.fastmcp import FastMCP\n\n"
        f'mcp = FastMCP("{name}")\n\n'
        + textwrap.dedent(body).strip()
        + '\n\n\nif __name__ == "__main__":\n    mcp.run()\n'
    )


GOOD = server(
    '''
    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Add two integers."""
        return str(a + b)
    '''
)
RAISES = server(
    '''
    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Always fails."""
        raise ValueError("upstream exploded")
    '''
)
CRASHES_ON_IMPORT = "import definitely_not_a_module_xyz\n" + GOOD
HANGS = server(
    '''
    import time

    @mcp.tool()
    def add(a: int, b: int) -> str:
        """Hangs."""
        time.sleep(60)
        return "never"
    '''
)
NO_TOOLS = server("x = 1")


def candidate(code: str, args: str = '{"a": 2, "b": 3}') -> GeneratedToolCandidate:
    return GeneratedToolCandidate(code=code, primary_tool="add", smoke_test_arguments_json=args)


# ---------------------------------------------------------------- static / helpers


def test_static_check_accepts_valid_server():
    assert static_check(GOOD) is None


@pytest.mark.parametrize(
    "code, fragment",
    [
        ("def f(:\n", "SyntaxError"),
        ("import os\nprint('hi')\n", "FastMCP"),
        (GOOD.replace('return str(a + b)', 'print(a); return str(a + b)'), "print"),
        ("import subprocess\n" + GOOD, "subprocess"),
        (GOOD.replace("    mcp.run()\n", "    pass\n"), "mcp.run()"),
    ],
)
def test_static_check_rejects(code, fragment):
    problem = static_check(code)
    assert problem and fragment in problem


def test_mock_arguments_uses_defaults_enums_and_types():
    schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["fast", "slow"]},
            "optional": {"type": "string", "default": "x"},
        },
        "required": ["limit", "query", "mode"],
    }
    assert mock_arguments(schema) == {"limit": 3, "query": "python", "mode": "fast"}


def test_clean_code_strips_fences():
    assert clean_code("```python\nx = 1\n```") == "x = 1\n"


def test_capability_request_normalizes_name():
    assert CapabilityRequest(tool_name="HackerNews", capability_description="x").tool_name == "hackernews_tool"
    with pytest.raises(ValueError):
        CapabilityRequest(tool_name="../evil", capability_description="x")


def test_sandbox_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    env = sandbox_env({"HN_API_BASE": "http://x"})
    assert "ANTHROPIC_API_KEY" not in env and "GITHUB_TOKEN" not in env
    assert env["HN_API_BASE"] == "http://x" and "PATH" in env


# ---------------------------------------------------------------- verifier (real subprocesses)


@pytest.fixture
def verifier(tmp_path: Path) -> ToolVerifier:
    return ToolVerifier(tmp_path / ".staging", timeout_s=15)


async def test_verifier_passes_good_server(verifier):
    report = await verifier.verify("math_tool", GOOD, primary_tool="add", smoke_arguments={"a": 2, "b": 3})
    assert report.ok, report.failure_summary()
    assert report.stage == "passed" and report.smoke_output == "5"
    assert [t.name for t in report.tools] == ["add"]


async def test_verifier_mocks_arguments_when_none_given(verifier):
    report = await verifier.verify("math_tool", GOOD)
    assert report.ok and report.smoke_arguments == {"a": 3, "b": 3}


async def test_verifier_reports_tool_exception(verifier):
    report = await verifier.verify("math_tool", RAISES, smoke_arguments={"a": 1, "b": 1})
    assert not report.ok and report.stage == "smoke_test"
    assert "upstream exploded" in report.error


async def test_verifier_captures_import_crash_stderr(verifier):
    report = await verifier.verify("math_tool", CRASHES_ON_IMPORT)
    assert not report.ok and report.stage == "startup"
    assert "definitely_not_a_module_xyz" in report.stderr
    assert report.duration_s < 15


async def test_verifier_rejects_server_without_tools(verifier):
    report = await verifier.verify("math_tool", NO_TOOLS)
    assert not report.ok and report.stage == "list_tools"


async def test_verifier_times_out(tmp_path):
    report = await ToolVerifier(tmp_path, timeout_s=4).verify("math_tool", HANGS, smoke_arguments={"a": 1, "b": 1})
    assert not report.ok and report.stage == "smoke_test" and "Timed out" in report.error


# ---------------------------------------------------------------- repair loop


def scripted_generator(drafts: list[str]) -> tuple[ScriptedProvider, list[str]]:
    prompts: list[str] = []
    it = iter(drafts)

    def structured(prompt, model):
        prompts.append(prompt)
        return candidate(next(it))

    return ScriptedProvider(chat=lambda m, t: LLMTurn(text=""), structured=structured), prompts


async def test_repair_loop_feeds_error_back_and_promotes(tmp_path):
    provider, prompts = scripted_generator([CRASHES_ON_IMPORT, GOOD])
    engine = SynthesisEngine(provider, tools_dir=tmp_path / "tools", verifier=ToolVerifier(tmp_path / "stg"))
    result = await engine.build_tool(CapabilityRequest(tool_name="math_tool", capability_description="add ints"))

    assert result.attempts == 2 and result.report.ok
    assert Path(result.path).read_text() == GOOD
    assert not (tmp_path / "stg" / "math_tool.py").exists()
    # The repair prompt contained the failing code and the captured traceback.
    assert "definitely_not_a_module_xyz" in prompts[1] and "failed automated verification" in prompts[1]


async def test_repair_loop_gives_up_after_max_retries(tmp_path):
    provider, prompts = scripted_generator([RAISES] * 4)
    engine = SynthesisEngine(provider, tools_dir=tmp_path / "tools", verifier=ToolVerifier(tmp_path / "stg"), max_retries=3)
    with pytest.raises(SynthesisError) as exc:
        await engine.build_tool(CapabilityRequest(tool_name="math_tool", capability_description="add ints"))
    assert exc.value.attempts == 4 and len(prompts) == 4
    assert not (tmp_path / "tools" / "math_tool.py").exists()


# ---------------------------------------------------------------- hot-loader / registry


async def test_dynamic_client_formats_schemas_and_calls(tmp_path):
    script = tmp_path / "math_tool.py"
    script.write_text(GOOD)
    async with DynamicMCPClient(script) as client:
        (anthropic_tool,) = client.anthropic_tools()
        (openai_tool,) = client.openai_tools()
        assert anthropic_tool["name"] == "math_tool__add"
        assert set(anthropic_tool["input_schema"]["properties"]) == {"a", "b"}
        assert openai_tool["type"] == "function" and openai_tool["function"]["name"] == "math_tool__add"
        result = await client.call_tool("add", {"a": 40, "b": 2})
        assert result.content[0].text == "42"
    assert not client.connected


async def test_registry_hot_loads_and_routes(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "math_tool.py").write_text(GOOD)
    (tools_dir / "broken_tool.py").write_text(CRASHES_ON_IMPORT)
    async with ToolRegistry(tools_dir) as registry:
        assert await registry.load_cached() == ["math_tool"]  # broken cache entry skipped
        ok = await registry.call("c1", "math_tool__add", {"a": 1, "b": 2})
        assert (ok.content, ok.is_error) == ("3", False)
        missing = await registry.call("c2", "nope__x", {})
        assert missing.is_error
    assert registry.servers == []


# ---------------------------------------------------------------- orchestrator end to end


async def test_orchestrator_synthesizes_then_uses_new_tool(tmp_path):
    seen_tool_sets: list[set[str]] = []

    def chat(messages, tools):
        names = {t["name"] for t in tools}
        seen_tool_sets.append(names)
        if len(seen_tool_sets) == 1:
            return LLMTurn(tool_calls=[ToolCall(id="s1", name=SYNTHESIZE_TOOL, arguments={
                "tool_name": "math_tool", "capability_description": "Add two integers."})])
        if len(seen_tool_sets) == 2:
            return LLMTurn(tool_calls=[ToolCall(id="c1", name="math_tool__add", arguments={"a": 20, "b": 22})])
        result = messages[-1]["content"][0]
        return LLMTurn(text=f"The answer is {result['content']}.")

    provider = ScriptedProvider(chat=chat, structured=lambda p, m: candidate(GOOD))
    tools_dir = tmp_path / "tools"
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=ToolVerifier(tmp_path / "stg"))
    async with ToolRegistry(tools_dir) as registry:
        run = await Orchestrator(provider, registry, engine).run("What is 20 + 22?")

    assert run.answer == "The answer is 42."
    assert run.synthesized == ["math_tool"]
    assert seen_tool_sets[0] == {SYNTHESIZE_TOOL}
    assert "math_tool__add" in seen_tool_sets[1]  # hot-loaded before the very next LLM call
    assert (tools_dir / "math_tool.py").exists()

    # Second run: the cached tool is mounted at startup, no synthesis needed.
    def chat2(messages, tools):
        if not isinstance(messages[-1]["content"], list):
            return LLMTurn(tool_calls=[ToolCall(id="c1", name="math_tool__add", arguments={"a": 1, "b": 1})])
        return LLMTurn(text=json.dumps(messages[-1]["content"][0]["content"]))

    def no_synthesis(p, m):
        raise AssertionError("should not synthesize when cached")

    provider2 = ScriptedProvider(chat=chat2, structured=no_synthesis)
    async with ToolRegistry(tools_dir) as registry:
        await registry.load_cached()
        run2 = await Orchestrator(provider2, registry, SynthesisEngine(provider2, tools_dir=tools_dir)).run("1+1?")
    assert run2.answer == '"2"' and run2.synthesized == []
