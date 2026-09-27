"""Self-healing synthesis loop: generate -> verify -> (repair -> verify)* -> promote."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from autotool.core.llm import LLMProvider
from autotool.core.schema import CapabilityRequest, SynthesisResult, VerificationReport
from autotool.synthesis.generator import ToolGenerator
from autotool.synthesis.verifier import ToolVerifier

log = logging.getLogger(__name__)


class SynthesisError(RuntimeError):
    def __init__(self, tool_name: str, attempts: int, report: VerificationReport) -> None:
        super().__init__(f"Could not synthesize '{tool_name}' after {attempts} attempt(s). {report.failure_summary(1500)}")
        self.tool_name = tool_name
        self.attempts = attempts
        self.report = report


class SynthesisEngine:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        tools_dir: str | Path = "tools",
        verifier: ToolVerifier | None = None,
        max_retries: int = 3,
    ) -> None:
        self.verifier = verifier or ToolVerifier()
        self.generator = ToolGenerator(provider, env_names=self.verifier.tool_env.names)
        self.tools_dir = Path(tools_dir).resolve()
        self.max_retries = max_retries

    def cached_path(self, tool_name: str) -> Path:
        return self.tools_dir / f"{tool_name}.py"

    async def build_tool(self, request: CapabilityRequest | str, *, tool_name: str | None = None) -> SynthesisResult:
        if isinstance(request, str):
            request = CapabilityRequest(tool_name=tool_name or "custom_tool", capability_description=request)

        candidate = await self.generator.generate(request)
        attempts = 0
        while True:
            attempts += 1
            report = await self.verifier.verify(
                request.tool_name,
                candidate.code,
                primary_tool=candidate.primary_tool,
                smoke_arguments=candidate.smoke_test_arguments(),
            )
            if report.ok:
                path = self._promote(request.tool_name, candidate.code)
                log.info("Verified %s in %d attempt(s) -> %s", request.tool_name, attempts, path)
                return SynthesisResult(tool_name=request.tool_name, path=str(path), attempts=attempts, report=report)

            if report.stage == "consent":  # the user said no (or cannot be asked): never retry or re-prompt
                raise SynthesisError(request.tool_name, attempts, report)
            reason = (report.error or "").strip().splitlines()
            log.warning("Attempt %d for %s failed at %s: %s", attempts, request.tool_name, report.stage, reason[-1] if reason else "")
            if attempts > self.max_retries:
                raise SynthesisError(request.tool_name, attempts, report)
            candidate = await self.generator.repair(request, candidate, report, attempt=attempts)

    def _promote(self, tool_name: str, code: str) -> Path:
        return promote(self.tools_dir, tool_name, code)


def promote(tools_dir: Path, tool_name: str, code: str) -> Path:
    """Atomically move verified code into the tools cache (unique temp file: two hosts may promote at once)."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    final = tools_dir / f"{tool_name}.py"
    fd, tmp = tempfile.mkstemp(dir=tools_dir, prefix=f".{tool_name}-", suffix=".tmp")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(code)
    os.replace(tmp, final)
    return final
