"""Ephemeral subprocess verifier: stages candidate code, launches it as an MCP
stdio server, and runs automated smoke tests through a real ``ClientSession``.

This is process isolation with a hard timeout and a scrubbed environment, plus
a static lint for obviously dangerous constructs. It is not a security sandbox
against actively malicious code; run AutoTool in a container for that."""

from __future__ import annotations

import ast
import asyncio
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from autotool.clients.dynamic_client import DynamicMCPClient, render_call_result, sandbox_env
from autotool.core.schema import MCPToolDescriptor, VerificationReport

_BANNED_MODULES = {"subprocess", "ctypes", "multiprocessing", "pty"}
_BANNED_CALLS = {"eval", "exec", "compile", "__import__"}
_BANNED_ATTRS = {("os", "system"), ("os", "popen"), ("os", "remove"), ("os", "unlink"), ("shutil", "rmtree")}


def static_check(code: str) -> str | None:
    """Return an error message if the code violates the tool contract."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"SyntaxError: {exc.msg} (line {exc.lineno}): {exc.text!r}"

    problems: list[str] = []
    imports_fastmcp = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "mcp.server.fastmcp":
            imports_fastmcp = imports_fastmcp or any(a.name == "FastMCP" for a in node.names)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                if n.split(".")[0] in _BANNED_MODULES:
                    problems.append(f"line {node.lineno}: importing '{n}' is not allowed")
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in _BANNED_CALLS:
                problems.append(f"line {node.lineno}: calling '{f.id}' is not allowed")
            if isinstance(f, ast.Name) and f.id == "print" and not any(k.arg == "file" for k in node.keywords):
                problems.append(f"line {node.lineno}: bare print() writes to stdout and corrupts the MCP stdio stream; log to sys.stderr")
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and (f.value.id, f.attr) in _BANNED_ATTRS:
                problems.append(f"line {node.lineno}: '{f.value.id}.{f.attr}' is not allowed")

    if not imports_fastmcp:
        problems.append("missing 'from mcp.server.fastmcp import FastMCP'")
    if not _has_main_guard_run(tree):
        problems.append("missing `if __name__ == \"__main__\": mcp.run()` entrypoint")
    return "; ".join(problems) or None


def _has_main_guard_run(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
            if any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
                for n in ast.walk(node)
            ):
                return True
    return False


def mock_arguments(schema: dict[str, Any]) -> dict[str, Any]:
    """Synthesize plausible arguments for the required fields of a JSON schema."""
    props: dict[str, Any] = schema.get("properties", {}) or {}
    args: dict[str, Any] = {}
    for name in schema.get("required", []) or []:
        args[name] = _mock_value(name, props.get(name, {}))
    return args


def _mock_value(name: str, spec: dict[str, Any]) -> Any:
    if "default" in spec:
        return spec["default"]
    if spec.get("enum"):
        return spec["enum"][0]
    if "anyOf" in spec:
        non_null = [s for s in spec["anyOf"] if s.get("type") != "null"]
        return _mock_value(name, non_null[0]) if non_null else None
    t = spec.get("type", "string")
    lname = name.lower()
    if t == "integer":
        return max(int(spec.get("minimum", 1)), min(3, int(spec.get("maximum", 3))))
    if t == "number":
        return float(spec.get("minimum", 1.0))
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    if "url" in lname:
        return "https://example.com"
    if lname in {"q", "query", "search", "term", "keyword"}:
        return "python"
    return "test"


class ToolVerifier:
    def __init__(
        self,
        staging_dir: str | Path = ".staging",
        *,
        timeout_s: float = 15.0,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        self.staging_dir = Path(staging_dir).resolve()
        self.timeout_s = timeout_s
        self.env_overrides = env_overrides or {}

    def stage(self, tool_name: str, code: str) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        path = self.staging_dir / f"{tool_name}.py"
        path.write_text(code, encoding="utf-8")
        return path

    async def verify(
        self,
        tool_name: str,
        code: str,
        *,
        primary_tool: str | None = None,
        smoke_arguments: dict[str, Any] | None = None,
    ) -> VerificationReport:
        started = time.monotonic()
        problem = static_check(code)
        if problem:
            return VerificationReport(ok=False, stage="static", error=problem, duration_s=time.monotonic() - started)

        path = self.stage(tool_name, code)
        state: dict[str, Any] = {"stage": "startup"}
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errlog:
            client = DynamicMCPClient(path, server_name=tool_name, env=sandbox_env(self.env_overrides), errlog=errlog)
            try:
                # asyncio.timeout (not wait_for) keeps connect/close in one task,
                # which anyio's task-bound cancel scopes in the MCP transport require.
                async with asyncio.timeout(self.timeout_s):
                    report = await self._exercise(client, state, primary_tool, smoke_arguments)
            except TimeoutError:
                report = self._fail(state, f"Timed out after {self.timeout_s:.0f}s during '{state['stage']}'")
            except Exception:  # noqa: BLE001 - every failure mode becomes repair input
                report = self._fail(state, traceback.format_exc(limit=6))
            finally:
                await client.close()
            report.stderr = client.read_stderr()
        report.duration_s = time.monotonic() - started
        return report

    @staticmethod
    def _fail(state: dict[str, Any], error: str) -> VerificationReport:
        return VerificationReport(
            ok=False,
            stage=state["stage"],
            error=error,
            tools=state.get("tools", []),
            smoke_tool=state.get("smoke_tool"),
            smoke_arguments=state.get("smoke_arguments"),
        )

    async def _exercise(
        self,
        client: DynamicMCPClient,
        state: dict[str, Any],
        primary_tool: str | None,
        smoke_arguments: dict[str, Any] | None,
    ) -> VerificationReport:
        state["stage"] = "startup"
        await client.connect()

        state["stage"] = "list_tools"
        tools: list[MCPToolDescriptor] = client.tools
        state["tools"] = tools
        if not tools:
            raise AssertionError("list_tools() returned no tools; decorate functions with @mcp.tool()")
        for t in tools:
            if t.input_schema.get("type") != "object":
                raise AssertionError(f"tool {t.name!r} has a non-object input schema: {t.input_schema}")

        state["stage"] = "smoke_test"
        by_name = {t.name: t for t in tools}
        target = by_name.get(primary_tool or "") or tools[0]
        args = smoke_arguments if smoke_arguments is not None else mock_arguments(target.input_schema)
        state["smoke_tool"], state["smoke_arguments"] = target.name, args

        result = await client.call_tool(target.name, args)
        output = render_call_result(result)
        if result.isError:
            raise AssertionError(f"Tool '{target.name}' raised an error for arguments {args}:\n{output}")
        if not output.strip():
            raise AssertionError(f"Tool '{target.name}' returned no text content for arguments {args}")

        return VerificationReport(
            ok=True, stage="passed", tools=tools, smoke_tool=target.name, smoke_arguments=args, smoke_output=output[:2000]
        )
