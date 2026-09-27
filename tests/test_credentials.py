"""Credential sources for the MCP server: host config (AUTOTOOL_KEY_*), OS keychain,
~/.autotool/.env and an explicit env file, with precedence and least-privilege stripping."""

from __future__ import annotations

import pytest

from autotool.core import credentials
from autotool.core.credentials import KEY_PREFIX, keychain_delete, keychain_names, keychain_set, load_tool_env


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        self.store.pop((service, name), None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "keyring", FakeKeyring())
    monkeypatch.setattr(credentials, "runtime_dotenv_names", lambda: [])
    return tmp_path / "home"


def test_sources_merge_with_host_over_keychain_over_home_over_file(home, tmp_path):
    home.mkdir()
    (home / ".env").write_text("SHARED_TOKEN=from-home-env-1234\nHOME_ONLY_KEY=home-value-12345\nOPENAI_API_KEY=sk-model\n")
    extra = tmp_path / "extra.env"
    extra.write_text("SHARED_TOKEN=from-file-12345678\nFILE_ONLY=file-value\n")
    keychain_set(home, "SHARED_TOKEN", "from-keychain-1234")
    keychain_set(home, "KEYCHAIN_ONLY_TOKEN", "keychain-value-1234")
    environ = {f"{KEY_PREFIX}SHARED_TOKEN": "from-host-12345678", "PATH": "x"}

    tool_env = load_tool_env(home, env_file=extra, environ=environ)

    assert tool_env.names == ["FILE_ONLY", "HOME_ONLY_KEY", "KEYCHAIN_ONLY_TOKEN", "SHARED_TOKEN"]
    assert tool_env.grant(["SHARED_TOKEN"]) == {"SHARED_TOKEN": "from-host-12345678"}
    assert tool_env.grant(["KEYCHAIN_ONLY_TOKEN"]) == {"KEYCHAIN_ONLY_TOKEN": "keychain-value-1234"}


def test_prefixed_host_vars_and_model_keys_never_reach_tools(home, monkeypatch):
    home.mkdir()
    (home / ".env").write_text("OPENAI_API_KEY=sk-model-key-123456\nPLAIN=plain-value\n")
    monkeypatch.setenv(f"{KEY_PREFIX}PARCEL_USER", "acct-1")
    monkeypatch.setenv("PLAIN", "plain-value")
    tool_env = load_tool_env(home)
    assert tool_env.names == ["PARCEL_USER", "PLAIN"]
    env = tool_env.env_for('REQUIRED_ENV = ["PARCEL_USER"]')
    assert env["PARCEL_USER"] == "acct-1"
    assert f"{KEY_PREFIX}PARCEL_USER" not in env and "PLAIN" not in env and "OPENAI_API_KEY" not in env


def test_missing_home_is_empty(home):
    assert load_tool_env(home, environ={}).names == []


def test_keychain_index_holds_names_only(home):
    keychain_set(home, "TAVILY_API_KEY", "tvly-secret-value-123")
    keychain_set(home, "COMPOSIO_API_KEY", "cmp-secret-value-123")
    assert keychain_names(home) == ["COMPOSIO_API_KEY", "TAVILY_API_KEY"]
    assert "tvly-secret-value-123" not in (home / "keys.json").read_text()
    keychain_delete(home, "TAVILY_API_KEY")
    assert keychain_names(home) == ["COMPOSIO_API_KEY"]
    assert load_tool_env(home, environ={}).names == ["COMPOSIO_API_KEY"]


def test_keychain_rejects_invalid_names(home):
    with pytest.raises(ValueError, match="variable name"):
        keychain_set(home, "not a name", "v")


def test_host_mcp_configs_are_protected_from_tools(home, monkeypatch, tmp_path):
    monkeypatch.setattr(credentials.Path, "home", lambda: tmp_path)
    protect = load_tool_env(home, environ={}).protect
    assert str(tmp_path / ".claude.json") in protect and str(tmp_path / ".codex" / "config.toml") in protect


def test_missing_os_keychain_does_not_break_the_server(home, monkeypatch, caplog):
    import keyring.errors

    home.mkdir()
    (home / "keys.json").write_text('["TAVILY_API_KEY"]')
    (home / ".env").write_text("OTHER_API_KEY=other-value-123456\n")

    def no_backend(*args):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(credentials.keyring, "get_password", no_backend)
    assert load_tool_env(home, environ={}).names == ["OTHER_API_KEY"]
    assert "keychain" in caplog.text.lower()


def test_keys_add_without_a_keychain_says_what_to_do(tmp_path, monkeypatch, capsys):
    import io

    import keyring.errors

    from autotool.cli import main

    def no_backend(*args):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setenv("AUTOTOOL_HOME", str(tmp_path))
    monkeypatch.setattr(credentials.keyring, "set_password", no_backend)
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-value\n"))
    assert main(["keys", "add", "TAVILY_API_KEY", "--stdin"]) == 1
    assert ".env" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AUTOTOOL_THING", "bad-name"])
def test_keys_add_refuses_names_tools_can_never_use(tmp_path, monkeypatch, capsys, name):
    import io

    from autotool.cli import main

    monkeypatch.setenv("AUTOTOOL_HOME", str(tmp_path))
    monkeypatch.setattr(credentials, "keyring", FakeKeyring())
    monkeypatch.setattr("sys.stdin", io.StringIO("value-123456789\n"))
    assert main(["keys", "add", name, "--stdin"]) == 1
    err = capsys.readouterr().err
    assert ("reserved" in err) if name.isupper() else ("variable name" in err)
    assert keychain_names(tmp_path) == []
