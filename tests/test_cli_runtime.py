"""Runtime detection and dispatch: the seams where cli.py picks ollama vs
llama.cpp. HTTP is faked at the httpx boundary; no server required."""

import numpy as np

import kultivait.cli as cli
from kultivait.config import Config


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_runtime_env_override_wins(monkeypatch):
    monkeypatch.setenv("KULTIVAIT_RUNTIME", "llamacpp")
    # no probing should even matter
    monkeypatch.setattr(cli, "_reachable", lambda url: False)
    assert cli._detect_runtime() == "llamacpp"


def test_runtime_prefers_ollama_when_both_reachable(monkeypatch):
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "_reachable", lambda url: True)
    assert cli._detect_runtime() == "ollama"


def test_runtime_falls_back_to_llamacpp_when_only_it_answers(monkeypatch):
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "_reachable", lambda url: "8080" in url)
    assert cli._detect_runtime() == "llamacpp"


def test_embed_batch_dispatches_to_openai_endpoint_for_llamacpp(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        # out-of-order indices: the OpenAI response carries an index per
        # embedding and must be re-sorted to match the input order
        return FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [1.0, 1.0]},
                    {"index": 0, "embedding": [0.0, 0.0]},
                ]
            }
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    config = Config(
        runtime="llamacpp",
        chat_base_url="http://localhost:8080",
        embed_model="nomic-embed-text-v1.5.Q8_0",
    )
    vecs = cli._embed_batch(config, ["a", "b"])
    assert seen["url"] == "http://localhost:8080/v1/embeddings"
    assert np.array_equal(vecs, np.array([[0.0, 0.0], [1.0, 1.0]]))


def test_embed_batch_uses_ollama_endpoint_and_embed_base_url(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        return FakeResponse({"embeddings": [[0.5, 0.5]]})

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    config = Config(embed_model="nomic-embed-text", embed_base_url="http://elsewhere:9999")
    cli._embed_batch(config, ["a"])
    # embed_base_url wins over chat_base_url when set
    assert seen["url"] == "http://elsewhere:9999/api/embed"


def test_distiller_uses_openai_chat_for_llamacpp(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"] = url
        seen["payload"] = json
        return FakeResponse(
            {"choices": [{"message": {"content": "<think>hmm</think>the brief"}}]}
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    config = Config(
        runtime="llamacpp",
        chat_base_url="http://localhost:8080",
        distill_model="qwen2.5-0.5b-instruct-q4_k_m",
    )
    generate = cli._distill_generate_for(config)
    assert generate("distill this") == "the brief"
    assert seen["url"] == "http://localhost:8080/v1/chat/completions"
    # num_ctx is an ollama option; the OpenAI payload must not carry it
    assert "options" not in seen["payload"]


def test_build_backends_with_api_tiers(monkeypatch):
    from kultivait.config import TierSpec
    from kultivait.api_backends import OpenRouterBackend, AnthropicBackend, OpenAIBackend

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-456")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("kultivait.credentials._get_keychain_key", lambda s, a: None)
    monkeypatch.setattr("kultivait.credentials._get_file_key", lambda p, credentials_path=None: None)

    config = Config(
        tiers=[
            TierSpec(name="router", role="frontier", kind="api", model="anthropic/claude-3.7-sonnet"),
            TierSpec(name="claude", role="frontier", kind="api", model="claude-3-7-sonnet-20250219"),
            TierSpec(name="openai", role="frontier", kind="api", model="gpt-4o"),
        ]
    )

    backends = cli.build_backends(config)
    assert isinstance(backends.get("router"), OpenRouterBackend)
    assert isinstance(backends.get("claude"), AnthropicBackend)
    # openai key is not resolvable -> not in backends (registered but not served)
    assert "openai" not in backends


def test_embed_batch_connect_error_provides_clean_exit(monkeypatch):
    import pytest
    import httpx

    def fake_post_fail(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(cli.httpx, "post", fake_post_fail)
    monkeypatch.setattr(cli, "_running_runtime", lambda: "ollama")

    config = Config(
        runtime="llamacpp",
        chat_base_url="http://localhost:8080",
        embed_model="nomic-embed-text-v1.5.Q8_0",
    )
    with pytest.raises(SystemExit) as exc:
        cli._embed_batch(config, ["a"])
    assert "Cannot connect to llama-server at http://localhost:8080" in str(exc.value)
    assert "ollama is currently running" in str(exc.value)


def test_cmd_serve_passes_configured_preprocess_generator(monkeypatch):
    import argparse

    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("kultivait.server.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_router", lambda c: None)
    monkeypatch.setattr(cli, "build_backends", lambda c: {})
    monkeypatch.setattr(cli, "build_gate", lambda c: None)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    config = Config(
        runtime="llamacpp",
        chat_base_url="http://localhost:8080",
        distill_model="my-distill-model",
    )
    monkeypatch.setattr(cli, "get_config", lambda: config)

    cli.cmd_serve(argparse.Namespace(port=4114))
    assert "preprocess_generate" in captured
    assert callable(captured["preprocess_generate"])


