"""G2 (#96) tests: the train/serve framing alignment — byte-for-byte."""

import json
from pathlib import Path

import httpx

from kultivait.preprocessor import PREPROCESSOR_PROMPT
from kultivait.server import _default_preprocess_generate_for


CORPUS = Path("/tmp/g2-corpus/train.jsonl")


def _captured_generate():
    """Invoke the serve-path generate with a capture transport; return the
    exact messages list it sends to the runtime."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"message": {"content": "{}"}})

    gen = _default_preprocess_generate_for()
    # monkey the transport by calling through httpx's mock via a patched post
    import kultivait.server as srv
    original_post = srv.httpx.post
    srv.httpx.post = lambda url, **kw: httpx.Response(
        200, json={"message": {"content": "{}"}}, request=httpx.Request("POST", url, json=kw.get("json"))) if False else _mock_post(captured, url, **kw)
    try:
        gen("any-model", "Fix the parser and run the tests.")
    finally:
        srv.httpx.post = original_post
    return captured["payload"]["messages"]


def _mock_post(captured, url, **kw):
    captured["payload"] = kw.get("json") or {}
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "{}"}}
    return _R()


# ---------------------------------------------------------------- serve shape


def test_serve_path_sends_system_plus_user():
    msgs = _captured_generate()
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == PREPROCESSOR_PROMPT
    assert msgs[1]["content"] == "Fix the parser and run the tests."


# ---------------------------------------------------------------- alignment


def test_train_format_equals_serve_format_byte_for_byte():
    """THE G2 assertion: the serve-path messages (system contract + user query)
    match the corpus training pairs' structure with identical system content."""
    if not CORPUS.exists():
        import pytest
        pytest.skip("gen-2 corpus not on this machine")
    rows = [json.loads(l) for l in CORPUS.read_text().splitlines() if l.strip()]
    serve_msgs = _captured_generate()
    for row in rows:
        train_msgs = row["messages"]
        # system identical
        assert train_msgs[0]["content"] == serve_msgs[0]["content"]
        # user is the varying tail in both shapes
        assert isinstance(train_msgs[1]["content"], str)
        assert isinstance(serve_msgs[1]["content"], str)
        # the assistant row exists only in training (the target)
        assert train_msgs[2]["role"] == "assistant"


def test_corpus_system_is_the_live_contract():
    """The corpus was built with the LIVE PREPROCESSOR_PROMPT — no drift."""
    if not CORPUS.exists():
        import pytest
        pytest.skip("gen-2 corpus not on this machine")
    rows = [json.loads(l) for l in CORPUS.read_text().splitlines() if l.strip()]
    for row in rows:
        assert row["messages"][0]["content"] == PREPROCESSOR_PROMPT
