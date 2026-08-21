"""runtimes: lifecycle for ollama and llama-server with hard mutual
exclusion — every process/network/brew access injected, nothing real."""

import httpx

import kultivait.runtimes as runtimes


class FakeHTTP:
    """Answers 200 for URLs under any of `up` prefixes; else 'down'."""

    def __init__(self, up=()):
        self.up = set(up)

    def __call__(self, url, timeout=None):
        if any(url.startswith(u) for u in self.up):
            return type("Resp", (), {"status_code": 200})()
        raise httpx.ConnectError("nothing listening")


def _ok(status):
    assert status == "up", status


def test_start_ollama_already_up_touches_nothing():
    cmds, procs = [], []
    http = FakeHTTP(up=(runtimes.OLLAMA_URL,))
    status = runtimes.start_ollama(
        run_cmd=cmds.append, popen=procs.append, http_get=http,
        which=lambda c: "/bin/brew" if c == "brew" else None, sleep=lambda s: None,
    )
    _ok(status)
    assert cmds == [] and procs == []


def test_start_ollama_prefers_brew_services_then_verifies():
    http = FakeHTTP()
    cmds = []

    def wake(seconds):
        http.up.add(runtimes.OLLAMA_URL)

    status = runtimes.start_ollama(
        run_cmd=cmds.append, popen=lambda p: None, http_get=http,
        which=lambda c: "/bin/brew" if c == "brew" else None, sleep=wake,
    )
    _ok(status)
    assert cmds == [["brew", "services", "start", "ollama"]]


def test_start_ollama_detached_fallback_without_brew():
    http = FakeHTTP()
    procs = []

    def popen(cmd, **kwargs):
        procs.append((cmd, kwargs))

    def wake(seconds):
        http.up.add(runtimes.OLLAMA_URL)

    status = runtimes.start_ollama(
        run_cmd=lambda c: None, popen=popen, http_get=http,
        which=lambda c: "/bin/ollama" if c == "ollama" else None, sleep=wake,
    )
    _ok(status)
    assert procs == [((["/bin/ollama", "serve"]), {"start_new_session": True})]


def test_start_ollama_without_brew_or_binary_fails_cleanly():
    procs = []
    status = runtimes.start_ollama(
        run_cmd=lambda c: None, popen=procs.append, http_get=FakeHTTP(),
        which=lambda c: None, sleep=lambda s: None,
    )
    assert status == "failed"
    assert procs == []


def test_stop_ollama_already_down_is_a_noop():
    cmds = []
    status = runtimes.stop_ollama(
        run_cmd=cmds.append, http_get=FakeHTTP(),
        which=lambda c: "/bin/brew", sleep=lambda s: None,
    )
    assert status == "down"
    assert cmds == []


def test_stop_ollama_escalates_brew_to_pkill():
    http = FakeHTTP(up=(runtimes.OLLAMA_URL,))
    cmds = []

    def die_after_pkill(seconds):
        if any(c[0] == "pkill" for c in cmds):
            http.up.clear()

    status = runtimes.stop_ollama(
        run_cmd=cmds.append, http_get=http,
        which=lambda c: "/bin/brew", sleep=die_after_pkill,
    )
    assert status == "down"
    assert ["brew", "services", "stop", "ollama"] in cmds
    assert ["pkill", "-x", "ollama"] in cmds  # brew stop alone didn't free the port


def test_stop_ollama_refuses_to_die_fails():
    http = FakeHTTP(up=(runtimes.OLLAMA_URL,))
    status = runtimes.stop_ollama(
        run_cmd=lambda c: None, http_get=http,
        which=lambda c: "/bin/brew", sleep=lambda s: None, deadline_s=1,
    )
    assert status == "failed"


def test_stop_llama_pkills_and_verifies():
    http = FakeHTTP(up=(runtimes.LLAMA_URL,))
    cmds = []

    def die(seconds):
        http.up.clear()

    status = runtimes.stop_llama(run_cmd=cmds.append, http_get=http, sleep=die)
    assert status == "down"
    assert ["pkill", "-x", "llama-server"] in cmds
