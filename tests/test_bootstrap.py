"""bootstrap: every side effect is injected — no subprocess, network, sudo,
or real home dir anywhere in these tests."""

from pathlib import Path
from types import SimpleNamespace

import kultivait.bootstrap as bootstrap


def _fail_cmd(*a, **k):  # a run_cmd that must never be reached
    raise AssertionError("run_cmd should not have been called")


def _fail_confirm(prompt):
    raise AssertionError("confirm should not have been called")


def test_ask_defaults_to_yes():
    assert bootstrap.ask("go?", input_fn=lambda _: "") is True
    assert bootstrap.ask("go?", input_fn=lambda _: "y") is True
    assert bootstrap.ask("go?", input_fn=lambda _: "N") is False


def test_ensure_llamacpp_present_short_circuits():
    which = lambda c: "/opt/homebrew/bin/llama-server" if c == "llama-server" else None
    state = bootstrap.ensure_llamacpp(confirm=_fail_confirm, run_cmd=_fail_cmd, which=which)
    assert state == "present"


def test_ensure_llamacpp_without_brew_goes_advisory(capsys):
    state = bootstrap.ensure_llamacpp(
        confirm=_fail_confirm, run_cmd=_fail_cmd, which=lambda c: None
    )
    assert state == "advisory"
    assert "Homebrew" in capsys.readouterr().out


def test_ensure_llamacpp_declined():
    which = lambda c: "/opt/homebrew/bin/brew" if c == "brew" else None
    state = bootstrap.ensure_llamacpp(confirm=lambda p: False, run_cmd=_fail_cmd, which=which)
    assert state == "declined"


def test_ensure_llamacpp_installs_via_brew():
    calls = []

    def run_cmd(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    which = lambda c: "/opt/homebrew/bin/brew" if c == "brew" else None
    state = bootstrap.ensure_llamacpp(confirm=lambda p: True, run_cmd=run_cmd, which=which)
    assert state == "installed"
    assert calls == [["brew", "install", "llama.cpp"]]


def test_ensure_llamacpp_reports_brew_failure():
    which = lambda c: "/opt/homebrew/bin/brew" if c == "brew" else None
    run_cmd = lambda cmd, **kw: SimpleNamespace(returncode=1)
    state = bootstrap.ensure_llamacpp(confirm=lambda p: True, run_cmd=run_cmd, which=which)
    assert state == "failed"


def test_models_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("KULTIVAIT_LLAMACPP_MODELS_DIR", str(tmp_path / "ggufs"))
    assert bootstrap.models_dir() == tmp_path / "ggufs"


def test_models_dir_default_is_llamacpp_cache(monkeypatch):
    monkeypatch.delenv("KULTIVAIT_LLAMACPP_MODELS_DIR", raising=False)
    monkeypatch.delenv("LLAMA_CACHE", raising=False)
    assert bootstrap.models_dir() == Path.home() / "Library" / "Caches" / "llama.cpp"


from kultivait.hardware import ModelPick, SetupPlan


class FakeStream:
    def __init__(self, status_code, body: bytes):
        self.status_code = status_code
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        assert self.status_code in (200, 206)

    def iter_bytes(self, chunk_size):
        for i in range(0, len(self._body), 3):  # tiny chunks to exercise the loop
            yield self._body[i : i + 3]


class FakeClient:
    """Serves `body`; honors Range unless ignore_range is set."""

    def __init__(self, body: bytes, ignore_range: bool = False):
        self.body = body
        self.ignore_range = ignore_range
        self.requests = []

    def stream(self, method, url, headers=None, follow_redirects=False):
        headers = dict(headers or {})
        self.requests.append((url, headers))
        if "Range" in headers and not self.ignore_range:
            offset = int(headers["Range"].removeprefix("bytes=").removesuffix("-"))
            return FakeStream(206, self.body[offset:])
        return FakeStream(200, self.body)


def _quiet(*args, **kwargs):
    pass


def pick(name="tiny.gguf", body=b"0123456789"):
    return ModelPick("reasoning", "x/y", name, len(body), 0)


def make_plan(*picks):
    return SetupPlan(eligible=True, reason="test", models=tuple(picks))


def test_download_writes_file_and_clears_part(tmp_path):
    body = b"0123456789"
    client = FakeClient(body)
    bootstrap._download(client, "http://x/tiny.gguf", tmp_path / "tiny.gguf", len(body), log=_quiet)
    assert (tmp_path / "tiny.gguf").read_bytes() == body
    assert not (tmp_path / "tiny.gguf.part").exists()


def test_download_resumes_from_part_with_range_header(tmp_path):
    body = b"0123456789"
    (tmp_path / "tiny.gguf.part").write_bytes(body[:4])
    client = FakeClient(body)
    bootstrap._download(client, "http://x/tiny.gguf", tmp_path / "tiny.gguf", len(body), log=_quiet)
    assert client.requests[0][1]["Range"] == "bytes=4-"
    assert (tmp_path / "tiny.gguf").read_bytes() == body


def test_download_restarts_when_server_ignores_range(tmp_path):
    body = b"0123456789"
    (tmp_path / "tiny.gguf.part").write_bytes(body[:4])
    client = FakeClient(body, ignore_range=True)
    bootstrap._download(client, "http://x/tiny.gguf", tmp_path / "tiny.gguf", len(body), log=_quiet)
    # a 200 despite our Range header means "here's the whole file": no dupes
    assert (tmp_path / "tiny.gguf").read_bytes() == body


def test_download_models_skips_complete_files(tmp_path):
    body = b"0123456789"
    (tmp_path / "tiny.gguf").write_bytes(body)
    client = FakeClient(body)
    ok = bootstrap.download_models(
        make_plan(pick()), tmp_path, confirm=_fail_confirm, client=client, log=_quiet
    )
    assert ok is True
    assert client.requests == []


def test_download_models_declined_downloads_nothing(tmp_path):
    client = FakeClient(b"0123456789")
    ok = bootstrap.download_models(
        make_plan(pick()), tmp_path, confirm=lambda p: False, client=client, log=_quiet
    )
    assert ok is False
    assert client.requests == []


def test_download_models_lists_sizes_before_confirming(tmp_path):
    lines = []

    def log(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    prompts = []

    def confirm(prompt):
        prompts.append(prompt)
        return True

    client = FakeClient(b"0123456789")
    bootstrap.download_models(make_plan(pick()), tmp_path, confirm=confirm, client=client, log=log)
    assert any("tiny.gguf" in line for line in lines)
    assert len(prompts) == 1 and "GB" in prompts[0]
    assert (tmp_path / "tiny.gguf").exists()
