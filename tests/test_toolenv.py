"""Offline tests for .env-discovered tool credentials: discovery, least-privilege
injection, redaction, and an end-to-end run against a local Bearer-auth API."""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import pytest

from autotool.clients.dynamic_client import sandbox_env
from autotool.core.llm import ScriptedProvider
from autotool.core.orchestrator import SYNTHESIZE_TOOL, SYSTEM_PROMPT, Orchestrator, system_prompt
from autotool.core.registry import ToolRegistry
from autotool.core.schema import CapabilityRequest, GeneratedToolCandidate, LLMTurn, ToolCall
from autotool.core.toolenv import ToolEnv, required_env
from autotool.synthesis.repair import SynthesisEngine
from autotool.synthesis.verifier import ToolVerifier, static_check
from tests.test_synthesis import GOOD, scripted_generator, server

ALPHA = "alpha-" + "a" * 20
BETA = "beta-" + "b" * 20


def env(**extra: str) -> ToolEnv:
    return ToolEnv({"ALPHA_API_KEY": ALPHA, "BETA_API_KEY": BETA, "PLAIN_SETTING": "hello", **extra})


# ---------------------------------------------------------------- discovery / grants


def test_from_dotenv_drops_reserved_and_empty(tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "OPENAI_API_KEY=sk-x\nANTHROPIC_API_KEY=a\nAUTOTOOL_MODEL=m\nEMPTY=\n\n"
        'TAVILY_API_KEY="tvly-quoted-value-123"\nexport PLAIN_SETTING=hello\n'
    )
    tool_env = ToolEnv.from_dotenv(f)
    assert tool_env.names == ["PLAIN_SETTING", "TAVILY_API_KEY"]
    assert tool_env.grant(["TAVILY_API_KEY"]) == {"TAVILY_API_KEY": "tvly-quoted-value-123"}


def test_from_dotenv_explicit_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ToolEnv.from_dotenv(tmp_path / "nope.env")


def test_grant_names_missing_and_available():
    with pytest.raises(LookupError, match="GAMMA_API_KEY.*available"):
        env().grant(["GAMMA_API_KEY"])


# ---------------------------------------------------------------- redaction


def test_redact_raw_encoded_and_heuristics():
    special = "k3y+with/special=chars-0123456789"
    odd = "tok_" + "z" * 20
    tool_env = ToolEnv({
        "SVC_API_KEY": special,
        "ODD_NAME": odd,                                     # token-shaped value under a non-secret name
        "AUTH_MODE": "on",                                   # too short to redact
        "BASE_URL": "https://api.example.com/v1/long/path",  # URL, not a token
        "CITY": "San Francisco",
    })
    text = (f"{special} {quote(special, safe='')} {quote_plus(special)} {quote(special)} "
            f"{special.replace('/', chr(92) + '/')} {odd} on https://api.example.com/v1/long/path San Francisco")
    out = tool_env.redact(text)
    assert out.count("[REDACTED:SVC_API_KEY]") == 5
    assert "[REDACTED:ODD_NAME]" in out
    assert " on " in out and "https://api.example.com/v1/long/path" in out and "San Francisco" in out
    assert tool_env.leaked(out) == [] and tool_env.leaked(text) == ["SVC_API_KEY", "ODD_NAME"]
    assert tool_env.redact(None) is None


def test_redact_longest_first():
    tool_env = ToolEnv({"A_TOKEN": "abcdefgh1234", "B_TOKEN": "abcdefgh1234-extended"})
    assert tool_env.redact("abcdefgh1234-extended") == "[REDACTED:B_TOKEN]"


# ---------------------------------------------------------------- REQUIRED_ENV


@pytest.mark.parametrize(
    "code, expected",
    [
        ('REQUIRED_ENV = ["A", "B", "A"]', ["A", "B"]),
        ('REQUIRED_ENV = ("A",)', ["A"]),
        ('REQUIRED_ENV: list[str] = ["A"]', ["A"]),
        ("x = 1", []),
    ],
)
def test_required_env_parses_literals(code, expected):
    assert required_env(code) == expected


def test_required_env_rejects_non_literal():
    with pytest.raises(ValueError, match="literal"):
        required_env("import os\nREQUIRED_ENV = list(os.environ)")


# ---------------------------------------------------------------- process environment


def test_sandbox_env_drops_tool_env_names(monkeypatch):
    monkeypatch.setenv("PLAIN_SETTING", "hello")
    assert "PLAIN_SETTING" not in sandbox_env(drop=["PLAIN_SETTING"])
    assert sandbox_env({"PLAIN_SETTING": "x"}, drop=["PLAIN_SETTING"])["PLAIN_SETTING"] == "x"


def test_env_for_grants_only_declared(monkeypatch):
    monkeypatch.setenv("BETA_API_KEY", BETA)  # present in the parent env too: must still be dropped
    granted = env().env_for('REQUIRED_ENV = ["ALPHA_API_KEY"]', {"X_API_BASE": "http://x"})
    assert granted["ALPHA_API_KEY"] == ALPHA and granted["X_API_BASE"] == "http://x"
    assert "BETA_API_KEY" not in granted and "PLAIN_SETTING" not in granted


PROBE = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def probe() -> str:
        """List the test variables this process can see."""
        names = {"ALPHA_API_KEY", "BETA_API_KEY", "PLAIN_SETTING"}
        return ",".join(sorted(k for k in os.environ if k.upper() in names))
    ''',
    name="probe_tool",
)
LEAKY = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def leak() -> str:
        """Fail with the key in the message, like an HTTP error that includes the request URL."""
        raise RuntimeError(f"401 for url https://api.example.com/v1?key={os.environ['ALPHA_API_KEY']}")
    ''',
    name="leaky_tool",
)


# ---------------------------------------------------------------- static check / verifier


def test_static_check_rejects_unavailable_env():
    problem = static_check(PROBE, ["BETA_API_KEY"])
    assert problem and "ALPHA_API_KEY" in problem and "BETA_API_KEY" in problem
    assert static_check(PROBE, ["ALPHA_API_KEY"]) is None
    assert static_check(PROBE) is None  # no availability check requested


def test_static_check_rejects_non_literal_declaration():
    assert "literal" in static_check(GOOD.replace("mcp = FastMCP", "REQUIRED_ENV = list('x')\nmcp = FastMCP"), [])


async def test_verifier_injects_only_declared_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAIN_SETTING", "hello")  # also in the parent env: must still be dropped
    verifier = ToolVerifier(tmp_path / "stg", tool_env=env())
    report = await verifier.verify("probe_tool", PROBE, primary_tool="probe", smoke_arguments={})
    assert report.ok, report.failure_summary()
    assert report.smoke_output == "ALPHA_API_KEY"


async def test_verifier_redacts_secret_in_error_and_stderr(tmp_path):
    report = await ToolVerifier(tmp_path / "stg", tool_env=env()).verify(
        "leaky_tool", LEAKY, primary_tool="leak", smoke_arguments={}
    )
    assert not report.ok and report.stage == "smoke_test"
    assert "[REDACTED:ALPHA_API_KEY]" in report.error
    assert ALPHA not in report.error + report.stderr + report.failure_summary()


async def test_verifier_rejects_unavailable_var_before_launch(tmp_path):
    report = await ToolVerifier(tmp_path / "stg", tool_env=ToolEnv()).verify("probe_tool", PROBE)
    assert not report.ok and report.stage == "static" and "ALPHA_API_KEY" in report.error


async def test_generator_prompt_lists_names_not_values(tmp_path):
    provider, prompts = scripted_generator([GOOD])
    verifier = ToolVerifier(tmp_path / "stg", tool_env=env())
    engine = SynthesisEngine(provider, tools_dir=tmp_path / "tools", verifier=verifier)
    await engine.build_tool(CapabilityRequest(tool_name="math_tool", capability_description="add ints"))
    assert "ALPHA_API_KEY" in prompts[0] and "REQUIRED_ENV" in prompts[0]
    assert ALPHA not in prompts[0]


def probe_server(name: str, var: str) -> str:
    return server(
        f'''
        import os

        REQUIRED_ENV = ["{var}"]

        @mcp.tool()
        def probe() -> str:
            """List the credential variables this process can see."""
            return ",".join(sorted(k for k in os.environ if k.upper().endswith("_API_KEY")))
        ''',
        name=name,
    )


ECHO = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def echo() -> str:
        """Return the key (a badly behaved tool)."""
        return "key=" + os.environ["ALPHA_API_KEY"]
    ''',
    name="echo_tool",
)


# ---------------------------------------------------------------- registry


async def test_registry_gives_each_tool_only_its_own_key(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "tavily_tool.py").write_text(probe_server("tavily_tool", "TAVILY_API_KEY"))
    (tools_dir / "composio_tool.py").write_text(probe_server("composio_tool", "COMPOSIO_API_KEY"))
    tool_env = ToolEnv({"TAVILY_API_KEY": "tvly-" + "t" * 20, "COMPOSIO_API_KEY": "cmp-" + "c" * 20})
    async with ToolRegistry(tools_dir, tool_env=tool_env) as registry:
        assert await registry.load_cached() == ["composio_tool", "tavily_tool"]
        assert (await registry.call("1", "tavily_tool__probe", {})).content == "TAVILY_API_KEY"
        assert (await registry.call("2", "composio_tool__probe", {})).content == "COMPOSIO_API_KEY"


async def test_registry_skips_cached_tool_whose_var_is_gone(tmp_path, caplog):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "tavily_tool.py").write_text(probe_server("tavily_tool", "TAVILY_API_KEY"))
    async with ToolRegistry(tools_dir, tool_env=ToolEnv()) as registry:
        assert await registry.load_cached() == []
    assert "TAVILY_API_KEY" in caplog.text


async def test_registry_redacts_tool_output(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "echo_tool.py").write_text(ECHO)
    async with ToolRegistry(tools_dir, tool_env=env()) as registry:
        await registry.load_cached()
        result = await registry.call("1", "echo_tool__echo", {})
    assert result.content == "key=[REDACTED:ALPHA_API_KEY]"


SECRET_DEFAULT = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def search(query: str, api_key: str = os.environ["ALPHA_API_KEY"]) -> str:
        """A common idiom that puts the key's value into the tool's input schema as a default."""
        return query
    ''',
    name="default_tool",
)
LONG_OUTPUT = server(
    '''
    import os

    REQUIRED_ENV = ["ALPHA_API_KEY"]

    @mcp.tool()
    def dump() -> str:
        """Output long enough that the key straddles the 2000-char smoke-output cut."""
        return "x" * 1990 + os.environ["ALPHA_API_KEY"]
    ''',
    name="long_tool",
)


async def test_registry_redacts_secret_in_tool_schema(tmp_path):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "default_tool.py").write_text(SECRET_DEFAULT)
    async with ToolRegistry(tools_dir, tool_env=env()) as registry:
        assert await registry.load_cached() == ["default_tool"]
        schema_text = json.dumps(registry.anthropic_tools())
        assert "[REDACTED:ALPHA_API_KEY]" in schema_text and env().leaked(schema_text) == []
        # Routing still works on the redacted descriptor.
        assert (await registry.call("1", "default_tool__search", {"query": "hi"})).content == "hi"


async def test_verifier_redacts_before_truncating_smoke_output(tmp_path):
    report = await ToolVerifier(tmp_path / "stg", tool_env=env()).verify(
        "long_tool", LONG_OUTPUT, primary_tool="dump", smoke_arguments={}
    )
    assert report.ok, report.failure_summary()
    assert ALPHA[:10] not in report.smoke_output


def test_env_for_strips_every_dotenv_name_even_unoffered_ones(monkeypatch):
    # Reserved, invalid and runtime-loaded (.env next to the package) names are never offered,
    # but they are in the parent env via load_dotenv and must not reach tools either.
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "admin-" + "k" * 20)
    monkeypatch.setenv("REPO_ONLY_SETTING", "repo-value")
    tool_env = ToolEnv({"OPENAI_ADMIN_KEY": "admin-" + "k" * 20, "ALPHA_API_KEY": ALPHA}, also_drop=["REPO_ONLY_SETTING"])
    granted = tool_env.env_for('REQUIRED_ENV = ["ALPHA_API_KEY"]')
    assert "OPENAI_ADMIN_KEY" not in granted and "REPO_ONLY_SETTING" not in granted
    assert granted["ALPHA_API_KEY"] == ALPHA


def test_from_dotenv_also_drops_the_runtime_loaded_file(tmp_path, monkeypatch):
    runtime_env = tmp_path / "runtime.env"
    runtime_env.write_text("REPO_ONLY_SETTING=repo-value\n")
    other = tmp_path / "other.env"
    other.write_text("ALPHA_API_KEY=" + ALPHA + "\n")
    monkeypatch.setattr("autotool.core.toolenv.find_dotenv", lambda usecwd=False: "" if usecwd else str(runtime_env))
    monkeypatch.setenv("REPO_ONLY_SETTING", "repo-value")
    tool_env = ToolEnv.from_dotenv(other)
    assert tool_env.names == ["ALPHA_API_KEY"]
    assert "REPO_ONLY_SETTING" not in tool_env.env_for("x = 1")


def test_system_prompt_lists_names_only_when_present():
    assert system_prompt([]) == SYSTEM_PROMPT
    prompt = system_prompt(["TAVILY_API_KEY"])
    assert "TAVILY_API_KEY" in prompt and prompt.startswith(SYSTEM_PROMPT)


# ---------------------------------------------------------------- end to end: Bearer-auth API

BEARER = "k3y+with/special=" + secrets.token_hex(8)  # URL-reserved chars on purpose


class _BearerAPI(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != f"Bearer {BEARER}":
            return self._send(401, {"error": "unauthorized"})
        city = parse_qs(urlparse(self.path).query).get("city", ["?"])[0]
        self._send(200, {"city": city, "temp_c": 21})

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def bearer_api():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _BearerAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


WEATHER_TOOL = server(
    '''
    import os

    import httpx

    REQUIRED_ENV = ["ACME_API_KEY"]
    API_BASE = os.environ.get("ACME_API_BASE", "https://api.acme.example")

    @mcp.tool()
    def current(city: str) -> str:
        """Current weather for a city."""
        with httpx.Client(timeout=10) as client:
            AUTH_LINE
            resp.raise_for_status()
            return resp.text
    ''',
    name="acme_tool",
)
# First draft puts the key in the query string (the server wants a header), so the 401
# error URL carries the key percent-encoded into the repair prompt unless redacted.
QUERY_DRAFT = WEATHER_TOOL.replace(
    "AUTH_LINE", 'resp = client.get(f"{API_BASE}/weather", params={"city": city, "key": os.environ["ACME_API_KEY"]})'
)
HEADER_DRAFT = WEATHER_TOOL.replace(
    "AUTH_LINE",
    'resp = client.get(f"{API_BASE}/weather", params={"city": city}, '
    'headers={"Authorization": "Bearer " + os.environ["ACME_API_KEY"]})',
)


class Recording(ScriptedProvider):
    """Scripted provider that also keeps every string it would send to an LLM."""

    def __init__(self, chat, structured) -> None:
        super().__init__(chat, structured)
        self.sent: list[str] = []

    async def complete(self, *, system, messages, tools):
        self.sent.append(json.dumps([system, messages, tools], default=str))
        return await super().complete(system=system, messages=messages, tools=tools)

    async def structured(self, *, system, prompt, output_model):
        self.sent.append(system + "\n" + prompt)
        return await super().structured(system=system, prompt=prompt, output_model=output_model)


async def test_end_to_end_bearer_api_repairs_without_leaking(tmp_path, bearer_api):
    drafts = iter([QUERY_DRAFT, HEADER_DRAFT])
    turns = 0

    def chat(messages, tools):
        nonlocal turns
        turns += 1
        if turns == 1:
            return LLMTurn(tool_calls=[ToolCall(id="s1", name=SYNTHESIZE_TOOL, arguments={
                "tool_name": "acme_tool", "capability_description": "Current weather from the Acme API (ACME_API_KEY)."})])
        if turns == 2:
            return LLMTurn(tool_calls=[ToolCall(id="c1", name="acme_tool__current", arguments={"city": "Paris"})])
        return LLMTurn(text=messages[-1]["content"][0]["content"])

    def structured(prompt, model):
        return GeneratedToolCandidate(code=next(drafts), primary_tool="current", smoke_test_arguments_json='{"city": "Paris"}')

    provider = Recording(chat, structured)
    tool_env = ToolEnv({"ACME_API_KEY": BEARER})
    overrides = {"ACME_API_BASE": bearer_api}
    tools_dir = tmp_path / "tools"
    verifier = ToolVerifier(tmp_path / "stg", env_overrides=overrides, tool_env=tool_env)
    engine = SynthesisEngine(provider, tools_dir=tools_dir, verifier=verifier)
    async with ToolRegistry(tools_dir, env_overrides=overrides, tool_env=tool_env) as registry:
        run = await Orchestrator(provider, registry, engine).run("Weather in Paris?")

    assert json.loads(run.answer) == {"city": "Paris", "temp_c": 21}
    synth = next(e.detail for e in run.events if e.kind == "synthesis")
    assert synth["ok"] and synth["attempts"] == 2
    sent = "\n".join(provider.sent)
    assert "ACME_API_KEY" in sent                # the name reaches the LLM ...
    assert "[REDACTED:ACME_API_KEY]" in sent     # ... the failed draft's error URL was scrubbed ...
    assert tool_env.leaked(sent) == []           # ... and no encoding of the value got through


def test_sandbox_env_is_an_allowlist(monkeypatch):
    # Hosts such as Claude Code pass their whole environment to MCP servers.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE0000")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@db/app")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:8080")
    monkeypatch.setenv("ACME_API_BASE", "http://127.0.0.1:1")
    env = sandbox_env()
    assert "AWS_ACCESS_KEY_ID" not in env and "DATABASE_URL" not in env
    assert env["HTTPS_PROXY"] == "http://proxy.local:8080" and env["ACME_API_BASE"] == "http://127.0.0.1:1"
    assert "PATH" in env


def test_reserved_values_are_redacted_but_never_granted():
    model_key = "sk-model-" + "m" * 24
    tool_env = ToolEnv({"OPENAI_API_KEY": model_key})
    assert tool_env.names == []
    assert tool_env.redact(f"read ../.env: OPENAI_API_KEY={model_key}") == "read ../.env: OPENAI_API_KEY=[REDACTED:OPENAI_API_KEY]"
