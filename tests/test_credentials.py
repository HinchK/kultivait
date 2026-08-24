import os
import stat
import subprocess
from pathlib import Path
import pytest

from kultivait.credentials import (
    _get_keychain_key,
    mask_key,
    resolve_provider_key,
    write_credentials,
)


def test_resolve_provider_key_env_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-secret-key")
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('[anthropic]\napi_key = "file-secret-key"\n')

    # Mock keychain to return keychain-key
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: "keychain-secret-key")

    # Env must win
    assert resolve_provider_key("anthropic", credentials_path=cred_file) == "env-secret-key"


def test_resolve_provider_key_keychain_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('[openai]\napi_key = "file-secret-key"\n')

    # Mock keychain returning valid key
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: "keychain-openai-key")

    # Keychain must win over file
    assert resolve_provider_key("openai", credentials_path=cred_file) == "keychain-openai-key"


def test_resolve_provider_key_file_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: None)

    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('[openrouter]\napi_key = "sk-or-v1-abc123xyz"\n')

    assert resolve_provider_key("openrouter", credentials_path=cred_file) == "sk-or-v1-abc123xyz"


def test_resolve_provider_key_none_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: None)

    cred_file = tmp_path / "credentials.toml"
    assert resolve_provider_key("anthropic", credentials_path=cred_file) is None


def test_write_credentials_and_permissions(tmp_path):
    cred_file = tmp_path / "sub" / "credentials.toml"

    write_credentials("anthropic", "sk-ant-test1", path=cred_file)
    write_credentials("openai", "sk-oai-test2", path=cred_file)

    assert cred_file.exists()
    # Check permissions 0600
    file_mode = stat.S_IMODE(cred_file.stat().st_mode)
    assert file_mode == 0o600

    content = cred_file.read_text()
    assert "[anthropic]" in content
    assert 'api_key = "sk-ant-test1"' in content
    assert "[openai]" in content
    assert 'api_key = "sk-oai-test2"' in content

    assert resolve_provider_key("anthropic", credentials_path=cred_file) == "sk-ant-test1"
    assert resolve_provider_key("openai", credentials_path=cred_file) == "sk-oai-test2"


def test_mask_key():
    assert mask_key(None) == ""
    assert mask_key("") == ""
    assert mask_key("1234567") == "****"
    assert mask_key("12345678") == "****"
    assert mask_key("sk-ant-api03-987654321") == "sk-a...4321"


def test_keychain_query_error_handling(monkeypatch):
    # Missing security binary
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert _get_keychain_key("kultivait", "anthropic") is None

    # Subprocess execution error / timeout
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/security")

    def mock_run_error(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="security", timeout=2.0)

    monkeypatch.setattr("subprocess.run", mock_run_error)
    assert _get_keychain_key("kultivait", "anthropic") is None

    # Non-zero returncode (key not found in keychain)
    class FakeResult:
        returncode = 44  # errSecItemNotFound
        stdout = ""
        stderr = "security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain."

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeResult())
    assert _get_keychain_key("kultivait", "anthropic") is None
