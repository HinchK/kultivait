# kultivait init: hardware scan + llama.cpp bootstrap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kultivait init` scans the machine, and on a bare Apple Silicon Mac with ≥24GB unified RAM offers to install llama.cpp (brew), download right-sized GGUFs, write a tuned launch script, and start the server — each step confirmed and idempotent.

**Architecture:** Two new modules mirror the repo's pure-core/side-effect-edges convention: `hardware.py` (pure `scan()`/`plan()`, fixture-testable like `config.detect()`) and `bootstrap.py` (confirmed, injected side effects). `cmd_init` composes them, then runs the existing survey → `config.toml` flow unchanged.

**Tech Stack:** Python ≥3.12, httpx (already a dependency), argparse, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-14-init-hardware-tuning-design.md` (approved). Read it before starting if anything here seems ambiguous.

## Global Constraints

- No new runtime dependencies — progress display is plain `print`, no rich/tqdm.
- Tests never touch network, subprocess, sudo, or the real home dir — inject fakes, use `tmp_path` (pattern: `tests/test_cli_runtime.py`, `tests/test_backends.py`).
- Match existing style: double quotes, string-literal type annotations like `"str | None"`, module docstrings explaining the *why*. No linter/formatter is configured.
- Constants (exact values, from the spec): `MIN_RAM_GB = 24.0`, `OS_RESERVE_MB = 8192`, `MARGIN_MB = 2048`, default GPU cap = ram_mb×2/3 when ram ≤36GB else ram_mb×3/4, server port `8080`, health URL `http://localhost:8080/v1/models`, 60s health deadline.
- Paths: GGUFs → `~/Library/Caches/llama.cpp` (respect `KULTIVAIT_LLAMACPP_MODELS_DIR` / `LLAMA_CACHE` overrides); artifacts → `~/.kultivait/llamacpp-presets.ini`, `~/.kultivait/start-llamacpp.sh`, `~/.kultivait/llamacpp.log`.
- Commit messages follow the repo's conventional style (`feat:`, `test:`, `docs:`); run `uv run pytest` before every commit.

---

### Task 1: `hardware.py` — `HardwareProfile` + `scan()`

**Files:**
- Create: `src/kultivait/hardware.py`
- Test: `tests/test_hardware.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces: `HardwareProfile(platform: str, chip: str, is_apple_silicon: bool, ram_gb: float)` (frozen dataclass) and `scan(sysctl_text: "str | None" = None, platform: "str | None" = None) -> HardwareProfile`. Task 2 adds `plan()` to this file; Task 7 calls `hardware.scan()` / `hardware.plan()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hardware.py`:

```python
"""hardware.scan()/plan(): pure parsing and sizing — fixture text in,
dataclasses out. No subprocess, no sysctl, no real machine."""

from kultivait.hardware import HardwareProfile, scan

M3_PRO_36GB = "machdep.cpu.brand_string: Apple M3 Pro\nhw.memsize: 38654705664\n"
M1_8GB = "machdep.cpu.brand_string: Apple M1\nhw.memsize: 8589934592\n"
M4_MAX_128GB = "machdep.cpu.brand_string: Apple M4 Max\nhw.memsize: 137438953472\n"
INTEL_16GB = (
    "machdep.cpu.brand_string: Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz\n"
    "hw.memsize: 17179869184\n"
)


def test_scan_parses_apple_silicon():
    p = scan(M3_PRO_36GB, platform="darwin")
    assert p == HardwareProfile("darwin", "Apple M3 Pro", True, 36.0)


def test_scan_m1_and_m4_brand_strings():
    assert scan(M1_8GB, platform="darwin").chip == "Apple M1"
    p = scan(M4_MAX_128GB, platform="darwin")
    assert p.is_apple_silicon and p.ram_gb == 128.0


def test_scan_intel_is_not_apple_silicon():
    p = scan(INTEL_16GB, platform="darwin")
    assert not p.is_apple_silicon
    assert p.ram_gb == 16.0


def test_scan_non_darwin_short_circuits():
    # never shells out off-macOS: passing no sysctl text must be safe
    p = scan(None, platform="linux")
    assert p == HardwareProfile("linux", "", False, 0.0)


def test_scan_garbled_text_yields_zeroes():
    p = scan("nonsense\nhw.memsize: not-a-number\n", platform="darwin")
    assert p.chip == "" and p.ram_gb == 0.0 and not p.is_apple_silicon
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hardware.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kultivait.hardware'`

- [ ] **Step 3: Write the implementation**

Create `src/kultivait/hardware.py`:

```python
"""Hardware survey: can this machine grow a local garden?

`scan()` parses sysctl output into a HardwareProfile and `plan()` (Task 2)
turns a profile into a SetupPlan — both pure, so any stranger's laptop is a
unit-test fixture, the same trick as config.detect(). The only subprocess
access lives in _read_sysctl().
"""

import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareProfile:
    platform: str  # sys.platform: "darwin" | "linux" | ...
    chip: str  # "Apple M3 Pro" | "Intel(R) Core(TM) ..." | ""
    is_apple_silicon: bool
    ram_gb: float  # hw.memsize / 2**30; 0.0 when unknown


def _read_sysctl() -> str:
    out = subprocess.run(
        ["sysctl", "machdep.cpu.brand_string", "hw.memsize"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout


def scan(
    sysctl_text: "str | None" = None, platform: "str | None" = None
) -> HardwareProfile:
    """Pure when given sysctl_text; only a live call (both args None on a
    Mac) shells out."""
    platform = platform or sys.platform
    if platform != "darwin":
        return HardwareProfile(platform=platform, chip="", is_apple_silicon=False, ram_gb=0.0)
    text = sysctl_text if sysctl_text is not None else _read_sysctl()
    chip, ram_gb = "", 0.0
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "machdep.cpu.brand_string":
            chip = value.strip()
        elif key.strip() == "hw.memsize":
            try:
                ram_gb = int(value.strip()) / 2**30
            except ValueError:
                ram_gb = 0.0
    return HardwareProfile(
        platform=platform,
        chip=chip,
        is_apple_silicon=chip.startswith("Apple "),
        ram_gb=ram_gb,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hardware.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/kultivait/hardware.py tests/test_hardware.py
git commit -m "feat: add hardware.scan() — pure sysctl parse into HardwareProfile"
```

---

### Task 2: `hardware.py` — model table + `plan()`

**Files:**
- Modify: `src/kultivait/hardware.py` (append)
- Test: `tests/test_hardware.py` (append)

**Interfaces:**
- Consumes: `HardwareProfile` from Task 1.
- Produces (used by Tasks 4–7):
  - `ModelPick(role, hf_repo, filename, approx_bytes, kv_bytes_per_token)` frozen dataclass with method `url() -> str`.
  - `SetupPlan(eligible: bool, reason: str, models: "tuple[ModelPick, ...]", ctx: int, server_flags: "tuple[str, ...]", default_gpu_cap_mb: int, wired_limit_mb: "int | None")` frozen dataclass.
  - `plan(profile: HardwareProfile) -> SetupPlan`
  - `default_gpu_cap_mb(ram_gb: float) -> int`
  - Module constants `MODEL_TABLE`, `EMBED_PICK`, `QWEN3_4B`, `QWEN3_8B`, `QWEN3_14B`, `QWEN3_32B_Q4`, `QWEN3_32B_Q5`, `MIN_RAM_GB`, `OS_RESERVE_MB`, `MARGIN_MB`, `CTX_LADDER`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hardware.py`:

```python
import kultivait.hardware as hw
from kultivait.hardware import default_gpu_cap_mb, plan


def prof(ram_gb, chip="Apple M3", platform="darwin"):
    return HardwareProfile(platform, chip, chip.startswith("Apple "), ram_gb)


def test_plan_ineligible_below_24gb():
    p = plan(prof(16))
    assert not p.eligible
    assert "16GB" in p.reason
    assert p.models == ()


def test_plan_eligible_at_exactly_24gb():
    assert plan(prof(24)).eligible


def test_plan_ineligible_intel():
    p = plan(prof(32, chip="Intel(R) Core(TM) i7"))
    assert not p.eligible
    assert "Apple Silicon" in p.reason


def test_plan_ineligible_non_darwin():
    p = plan(prof(64, platform="linux"))
    assert not p.eligible
    assert "macOS" in p.reason


def test_plan_24gb_tier_picks_and_ctx():
    p = plan(prof(24))
    assert [m.filename for m in p.models] == [
        "Qwen3-4B-Q4_K_M.gguf",
        "Qwen3-14B-Q4_K_M.gguf",
        "nomic-embed-text-v1.5.Q8_0.gguf",
    ]
    assert p.ctx == 16384
    # 24GB default cap (2/3 of 24576MB) comfortably holds the picks: no bump
    assert p.default_gpu_cap_mb == 16384
    assert p.wired_limit_mb is None


def test_plan_64gb_tier_gets_bigger_picks():
    p = plan(prof(64))
    assert [m.filename for m in p.models][:2] == [
        "Qwen3-8B-Q4_K_M.gguf",
        "Qwen3-32B-Q5_K_M.gguf",
    ]
    assert p.ctx == 32768
    assert p.wired_limit_mb is None


def test_default_gpu_cap_boundary_at_36gb():
    assert default_gpu_cap_mb(24) == 16384  # 2/3 of 24576
    assert default_gpu_cap_mb(36) == 24576  # still 2/3 at the boundary
    assert default_gpu_cap_mb(48) == 36864  # 3/4 of 49152


def test_plan_url_is_hf_resolve():
    p = plan(prof(24))
    assert p.models[0].url() == (
        "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
    )


def test_server_flags_carry_tuning_and_ctx():
    flags = plan(prof(32)).server_flags
    assert "--jinja" in flags and "-fa" in flags
    assert ("q8_0" in flags) and ("-c" in flags)
    assert flags[flags.index("-c") + 1] == "32768"
    assert flags[flags.index("--port") + 1] == "8080"


def test_ctx_steps_down_and_wired_limit_offered_when_tight(monkeypatch):
    # Synthetic 32-GiB reasoning pick on a 48GB machine: at ctx 32768 the
    # budget (41,689MB) blows the hard cap (49152-8192=40960MB) -> step to
    # 16384 (39,513MB); that still exceeds the default cap (36,864MB), so a
    # wired-limit bump is suggested, rounded up to a GB: 39,936MB.
    fat = hw.ModelPick("reasoning", "x/y", "fat.gguf", 32 * 2**30, 139_264)
    monkeypatch.setattr(hw, "MODEL_TABLE", [(48, hw.QWEN3_4B, fat, 32768)])
    p = plan(prof(48))
    assert p.eligible
    assert p.ctx == 16384
    assert p.wired_limit_mb == 39936
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hardware.py -v`
Expected: Task 1 tests pass; new tests FAIL with `ImportError: cannot import name 'default_gpu_cap_mb'`

- [ ] **Step 3: Write the implementation**

Append to `src/kultivait/hardware.py`:

```python
MIN_RAM_GB = 24.0
OS_RESERVE_MB = 8192  # leave >=8GB of unified memory for macOS
MARGIN_MB = 2048  # activations + slack on top of weights + KV
CTX_LADDER = [32768, 16384, 8192]
HF_BASE = "https://huggingface.co"


@dataclass(frozen=True)
class ModelPick:
    role: str  # "simple" | "reasoning" | "embed"
    hf_repo: str
    filename: str
    approx_bytes: int  # exact size on HF; also the "already downloaded" check
    kv_bytes_per_token: int  # q8_0 K+V per token; 0 for embedding models

    def url(self) -> str:
        return f"{HF_BASE}/{self.hf_repo}/resolve/main/{self.filename}"


EMBED_PICK = ModelPick(
    role="embed",
    hf_repo="nomic-ai/nomic-embed-text-v1.5-GGUF",
    filename="nomic-embed-text-v1.5.Q8_0.gguf",
    approx_bytes=146_146_432,
    kv_bytes_per_token=0,
)

# kv_bytes_per_token = 2 (K+V) x 8 kv-heads x 128 head-dim x n_layers x
# 1.0625 (q8_0 bytes/elem): Qwen3 4B/8B have 36 layers, 14B has 40, 32B has 64.
QWEN3_4B = ModelPick("simple", "Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", 2_497_280_256, 78_336)
QWEN3_8B = ModelPick("simple", "Qwen/Qwen3-8B-GGUF", "Qwen3-8B-Q4_K_M.gguf", 5_027_783_488, 78_336)
QWEN3_14B = ModelPick("reasoning", "Qwen/Qwen3-14B-GGUF", "Qwen3-14B-Q4_K_M.gguf", 9_001_752_960, 87_040)
QWEN3_32B_Q4 = ModelPick("reasoning", "Qwen/Qwen3-32B-GGUF", "Qwen3-32B-Q4_K_M.gguf", 19_762_149_024, 139_264)
QWEN3_32B_Q5 = ModelPick("reasoning", "Qwen/Qwen3-32B-GGUF", "Qwen3-32B-Q5_K_M.gguf", 23_214_831_232, 139_264)

# (min_ram_gb, simple pick, reasoning pick, ctx) — first row whose floor the
# machine clears wins, so keep this sorted largest-first.
MODEL_TABLE = [
    (64, QWEN3_8B, QWEN3_32B_Q5, 32768),
    (48, QWEN3_4B, QWEN3_32B_Q4, 32768),
    (32, QWEN3_4B, QWEN3_14B, 32768),
    (24, QWEN3_4B, QWEN3_14B, 16384),
]


@dataclass(frozen=True)
class SetupPlan:
    eligible: bool
    reason: str  # human-readable: why, or why not
    models: "tuple[ModelPick, ...]" = ()
    ctx: int = 0
    server_flags: "tuple[str, ...]" = ()
    default_gpu_cap_mb: int = 0
    wired_limit_mb: "int | None" = None  # None: default cap suffices


def default_gpu_cap_mb(ram_gb: float) -> int:
    """macOS caps GPU-usable unified memory at ~2/3 of RAM (<=36GB) or ~3/4
    (>36GB); iogpu.wired_limit_mb raises it."""
    ram_mb = int(ram_gb * 1024)
    return ram_mb * 2 // 3 if ram_gb <= 36 else ram_mb * 3 // 4


def _budget_mb(models: "tuple[ModelPick, ...]", ctx: int) -> int:
    weights = sum(m.approx_bytes for m in models)
    kv = max((m.kv_bytes_per_token for m in models), default=0) * ctx
    return (weights + kv) // 2**20 + MARGIN_MB


def plan(profile: HardwareProfile) -> SetupPlan:
    if profile.platform != "darwin":
        return SetupPlan(False, f"local-model setup is macOS-only (this is {profile.platform})")
    if not profile.is_apple_silicon:
        return SetupPlan(
            False, f"needs Apple Silicon; this Mac reports {profile.chip or 'an unknown CPU'}"
        )
    if profile.ram_gb < MIN_RAM_GB:
        return SetupPlan(
            False,
            f"needs >={MIN_RAM_GB:.0f}GB unified RAM; this Mac has {profile.ram_gb:.0f}GB",
        )
    _, simple, reasoning, ctx = next(r for r in MODEL_TABLE if profile.ram_gb >= r[0])
    models = (simple, reasoning, EMBED_PICK)
    hard_cap_mb = int(profile.ram_gb * 1024) - OS_RESERVE_MB
    # the plan must always fit RAM minus the OS reserve: step the context
    # down before ever suggesting a wired-limit bump can't-fit territory
    while _budget_mb(models, ctx) > hard_cap_mb and ctx != CTX_LADDER[-1]:
        ctx = CTX_LADDER[CTX_LADDER.index(ctx) + 1]
    cap = default_gpu_cap_mb(profile.ram_gb)
    budget = _budget_mb(models, ctx)
    wired = min(-(-budget // 1024) * 1024, hard_cap_mb) if budget > cap else None
    flags = (
        "--jinja",
        "-ngl", "99",
        "-fa", "on",
        "--cache-type-k", "q8_0",
        "--cache-type-v", "q8_0",
        "-c", str(ctx),
        "-b", "2048",
        "-ub", "2048",
        "--port", "8080",
    )
    return SetupPlan(
        eligible=True,
        reason=f"{profile.chip} with {profile.ram_gb:.0f}GB unified RAM",
        models=models,
        ctx=ctx,
        server_flags=flags,
        default_gpu_cap_mb=cap,
        wired_limit_mb=wired,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hardware.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/kultivait/hardware.py tests/test_hardware.py
git commit -m "feat: add hardware.plan() — per-RAM model table and tuned llama.cpp flags"
```

---

### Task 3: `bootstrap.py` — `ask()` + `ensure_llamacpp()`

**Files:**
- Create: `src/kultivait/bootstrap.py`
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `SetupPlan`/`ModelPick` from Task 2 (imported; used from Task 4 on).
- Produces (used by Tasks 4–7):
  - `ask(prompt: str, input_fn=input) -> bool` — `[Y/n]`, default yes.
  - `ensure_llamacpp(confirm=ask, run_cmd=subprocess.run, which=shutil.which) -> str` returning `"present" | "advisory" | "declined" | "installed" | "failed"`.
  - `models_dir() -> Path` — GGUF cache dir with env overrides.
  - Constant `BREW_INSTALL_HINT`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bootstrap.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kultivait.bootstrap'`

- [ ] **Step 3: Write the implementation**

Create `src/kultivait/bootstrap.py`:

```python
"""Zero-to-local bootstrap: install llama.cpp, download right-sized GGUFs,
write tuned launch artifacts, start the server.

Every step is idempotent (already-satisfied work is skipped, so re-running
`kultivait init` converges) and asks before mutating. All process, network,
and filesystem access is injected so tests never touch the real system.
"""

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import httpx

from kultivait.hardware import SetupPlan

BREW_INSTALL_HINT = (
    "Homebrew is required to install llama.cpp automatically.\n"
    "Install it first:\n"
    '  /bin/bash -c "$(curl -fsSL '
    'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n'
)


def ask(prompt: str, input_fn=input) -> bool:
    """[Y/n] confirm, default yes — every step was already offered explicitly."""
    return input_fn(f"{prompt} [Y/n] ").strip().lower() in ("", "y", "yes")


def models_dir() -> Path:
    """Same GGUF cache llama-server uses and cli._gguf_dirs() scans."""
    override = os.environ.get("KULTIVAIT_LLAMACPP_MODELS_DIR") or os.environ.get(
        "LLAMA_CACHE"
    )
    if override:
        return Path(override)
    return Path.home() / "Library" / "Caches" / "llama.cpp"


def ensure_llamacpp(confirm=ask, run_cmd=subprocess.run, which=shutil.which) -> str:
    """Idempotent install step: "present" | "advisory" | "declined" |
    "installed" | "failed"."""
    if which("llama-server"):
        return "present"
    if not which("brew"):
        print(BREW_INSTALL_HINT)
        return "advisory"
    if not confirm("Install llama.cpp via Homebrew (brew install llama.cpp)?"):
        return "declined"
    result = run_cmd(["brew", "install", "llama.cpp"])
    return "installed" if result.returncode == 0 else "failed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/kultivait/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add bootstrap install step — brew-or-advisory, confirmed, idempotent"
```

---

### Task 4: `bootstrap.py` — resumable GGUF downloads

**Files:**
- Modify: `src/kultivait/bootstrap.py` (append)
- Test: `tests/test_bootstrap.py` (append)

**Interfaces:**
- Consumes: `SetupPlan.models` (`ModelPick.url()`, `.filename`, `.approx_bytes`) from Task 2.
- Produces (used by Task 6's `run()`):
  - `download_models(plan: SetupPlan, dest: Path, confirm=ask, client: "httpx.Client | None" = None, log=print) -> bool` — False when the user declines.
  - `_download(client, url: str, dest: Path, expected_bytes: int, log=print) -> None` — streams to `<name>.gguf.part`, resumes via HTTP Range, renames when complete.
- Note: `log` is always called like `print` (positional strings, optional `end=` kwarg) — fakes must accept `*args, **kwargs`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bootstrap.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: Task 3 tests pass; new tests FAIL with `AttributeError: module 'kultivait.bootstrap' has no attribute '_download'`

- [ ] **Step 3: Write the implementation**

Append to `src/kultivait/bootstrap.py`:

```python
CHUNK = 1 << 20


def _download(client, url: str, dest: Path, expected_bytes: int, log=print) -> None:
    """Stream to <dest>.part, resume via Range, rename when complete."""
    if dest.exists() and dest.stat().st_size == expected_bytes:
        log(f"  {dest.name}: already present")
        return
    part = dest.with_name(dest.name + ".part")
    headers, mode = {}, "wb"
    if part.exists():
        headers["Range"] = f"bytes={part.stat().st_size}-"
        mode = "ab"
    with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
        if r.status_code == 200 and mode == "ab":
            mode = "wb"  # server ignored Range: start over rather than duplicate
        r.raise_for_status()
        done = part.stat().st_size if mode == "ab" else 0
        with open(part, mode) as f:
            for chunk in r.iter_bytes(CHUNK):
                f.write(chunk)
                done += len(chunk)
                log(
                    f"\r  {dest.name}: {done / 2**20:.0f}/{expected_bytes / 2**20:.0f} MB",
                    end="",
                )
        log("")
    part.rename(dest)


def download_models(
    plan: SetupPlan,
    dest: Path,
    confirm=ask,
    client: "httpx.Client | None" = None,
    log=print,
) -> bool:
    """Confirm once (sizes shown), then fetch whatever isn't already on disk."""
    todo = [
        m
        for m in plan.models
        if not (dest / m.filename).exists()
        or (dest / m.filename).stat().st_size != m.approx_bytes
    ]
    if not todo:
        return True
    log("models to download:")
    for m in todo:
        log(f"  {m.filename}  ({m.approx_bytes / 2**30:.1f} GB)")
    total_gb = sum(m.approx_bytes for m in todo) / 2**30
    if not confirm(f"Download {total_gb:.1f} GB into {dest}?"):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    client = client or httpx.Client(timeout=60)
    for m in todo:
        _download(client, m.url(), dest / m.filename, m.approx_bytes, log=log)
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/kultivait/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: add resumable GGUF downloads with one up-front size confirm"
```

---

### Task 5: `bootstrap.py` — launch artifacts (presets INI + start script)

**Files:**
- Modify: `src/kultivait/bootstrap.py` (append)
- Test: `tests/test_bootstrap.py` (append)

**Interfaces:**
- Consumes: `SetupPlan.models` / `.server_flags` / `.wired_limit_mb` / `.default_gpu_cap_mb` from Task 2.
- Produces (used by Task 6's `run()` and by the generated system):
  - `write_artifacts(plan: SetupPlan, kultivait_home: Path, gguf_dir: Path) -> "tuple[Path, Path]"` returning `(preset_path, script_path)`; always regenerates both files from the plan.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bootstrap.py`:

```python
def full_plan(wired=None):
    return SetupPlan(
        eligible=True,
        reason="test",
        models=(
            ModelPick("simple", "Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", 10, 78_336),
            ModelPick(
                "embed",
                "nomic-ai/nomic-embed-text-v1.5-GGUF",
                "nomic-embed-text-v1.5.Q8_0.gguf",
                10,
                0,
            ),
        ),
        ctx=16384,
        server_flags=("--jinja", "-fa", "on", "-c", "16384", "--port", "8080"),
        default_gpu_cap_mb=16384,
        wired_limit_mb=wired,
    )


def test_write_artifacts_ini_marks_embedding_model(tmp_path):
    preset, _ = bootstrap.write_artifacts(full_plan(), tmp_path / "home", tmp_path / "ggufs")
    text = preset.read_text()
    assert "[nomic-embed-text-v1.5.Q8_0]" in text
    assert "embedding = 1" in text
    assert str(tmp_path / "ggufs" / "nomic-embed-text-v1.5.Q8_0.gguf") in text


def test_write_artifacts_script_is_executable_with_flags_and_log(tmp_path):
    _, script = bootstrap.write_artifacts(full_plan(), tmp_path / "home", tmp_path / "ggufs")
    text = script.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "--models-dir" in text and "--models-preset" in text
    assert "-c 16384" in text
    assert "llamacpp.log" in text
    assert script.stat().st_mode & 0o111  # executable


def test_write_artifacts_sysctl_only_as_comment_and_only_when_suggested(tmp_path):
    _, without = bootstrap.write_artifacts(full_plan(), tmp_path / "h1", tmp_path / "g")
    assert "iogpu.wired_limit_mb" not in without.read_text()
    _, with_bump = bootstrap.write_artifacts(full_plan(wired=39936), tmp_path / "h2", tmp_path / "g")
    lines = [l for l in with_bump.read_text().splitlines() if "iogpu.wired_limit_mb" in l]
    assert lines and all(l.startswith("#") for l in lines)
    assert "iogpu.wired_limit_mb=39936" in lines[0].replace(" ", "")


def test_write_artifacts_regenerates_on_rerun(tmp_path):
    home = tmp_path / "home"
    bootstrap.write_artifacts(full_plan(), home, tmp_path / "g")
    plan2 = full_plan(wired=39936)
    _, script = bootstrap.write_artifacts(plan2, home, tmp_path / "g")
    assert "iogpu.wired_limit_mb" in script.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: earlier tests pass; new tests FAIL with `AttributeError: ... 'write_artifacts'`

- [ ] **Step 3: Write the implementation**

Append to `src/kultivait/bootstrap.py`:

```python
def write_artifacts(
    plan: SetupPlan, kultivait_home: Path, gguf_dir: Path
) -> "tuple[Path, Path]":
    """Presets INI + start script, regenerated from the plan every run —
    like config.toml, these are decisions made visible, not precious state."""
    kultivait_home.mkdir(parents=True, exist_ok=True)
    embed = next(m for m in plan.models if m.role == "embed")
    preset = kultivait_home / "llamacpp-presets.ini"
    preset.write_text(
        "# generated by kultivait init — regenerate by re-running it\n"
        f"[{embed.filename.removesuffix('.gguf')}]\n"
        f"model = {gguf_dir / embed.filename}\n"
        "embedding = 1\n"
    )
    script = kultivait_home / "start-llamacpp.sh"
    log_path = kultivait_home / "llamacpp.log"
    sysctl_comment = ""
    if plan.wired_limit_mb:
        sysctl_comment = (
            "# Optional: raise the GPU memory cap from "
            f"~{plan.default_gpu_cap_mb} MB (resets on reboot):\n"
            f"#   sudo sysctl iogpu.wired_limit_mb={plan.wired_limit_mb}\n"
        )
    script.write_text(
        "#!/bin/sh\n"
        "# generated by kultivait init — regenerate by re-running it\n"
        f"{sysctl_comment}"
        f'exec llama-server --models-dir "{gguf_dir}" --models-preset "{preset}" \\\n'
        f"  {' '.join(plan.server_flags)} \\\n"
        f'  >> "{log_path}" 2>&1\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return preset, script
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/kultivait/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: generate tuned llama-server presets INI and start script"
```

---

### Task 6: `bootstrap.py` — wired-limit offer, server start, `run()` orchestrator

**Files:**
- Modify: `src/kultivait/bootstrap.py` (append)
- Test: `tests/test_bootstrap.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 3–5.
- Produces (used by Task 7):
  - `offer_wired_limit(plan, confirm=ask, run_cmd=subprocess.run, log=print) -> bool`
  - `start_server(script: Path, popen=subprocess.Popen, http_get=httpx.get, sleep=time.sleep, deadline_s: int = 60, log=print) -> bool`
  - `run(plan: SetupPlan, *, home: "Path | None" = None, gguf_dir: "Path | None" = None, confirm=ask, run_cmd=subprocess.run, which=shutil.which, popen=subprocess.Popen, http_get=httpx.get, sleep=time.sleep, client=None, log=print, skip_install: bool = False) -> str` returning `"ok" | "aborted" | "server_failed"`.
  - `HEALTH_URL = "http://localhost:8080/v1/models"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bootstrap.py`:

```python
import httpx


def test_offer_wired_limit_noop_when_plan_fits():
    assert bootstrap.offer_wired_limit(full_plan(), confirm=_fail_confirm, run_cmd=_fail_cmd) is False


def test_offer_wired_limit_declined_runs_nothing():
    ok = bootstrap.offer_wired_limit(
        full_plan(wired=39936), confirm=lambda p: False, run_cmd=_fail_cmd, log=_quiet
    )
    assert ok is False


def test_offer_wired_limit_runs_sysctl_when_accepted():
    calls = []

    def run_cmd(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    ok = bootstrap.offer_wired_limit(
        full_plan(wired=39936), confirm=lambda p: True, run_cmd=run_cmd, log=_quiet
    )
    assert ok is True
    assert calls == [["sudo", "sysctl", "iogpu.wired_limit_mb=39936"]]


def _script(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    script = home / "start-llamacpp.sh"
    script.write_text("#!/bin/sh\n")
    return script


def test_start_server_polls_until_healthy(tmp_path):
    script = _script(tmp_path)
    popped, attempts = [], iter([httpx.ConnectError("boom"), httpx.ConnectError("boom"), None])

    def http_get(url, timeout=None):
        nxt = next(attempts)
        if nxt:
            raise nxt
        return SimpleNamespace(status_code=200)

    ok = bootstrap.start_server(
        script,
        popen=lambda cmd, **kw: popped.append(cmd),
        http_get=http_get,
        sleep=lambda s: None,
        log=_quiet,
    )
    assert ok is True
    assert popped == [["/bin/sh", str(script)]]


def test_start_server_timeout_tails_log(tmp_path):
    script = _script(tmp_path)
    (script.parent / "llamacpp.log").write_text("line1\nfatal: metal init failed\n")
    lines = []

    def log(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    def http_get(url, timeout=None):
        raise httpx.ConnectError("still down")

    ok = bootstrap.start_server(
        script, popen=lambda cmd, **kw: None, http_get=http_get, sleep=lambda s: None,
        deadline_s=6, log=log,
    )
    assert ok is False
    assert any("metal init failed" in line for line in lines)
    assert any(str(script) in line for line in lines)


def _run_kwargs(tmp_path, **over):
    """run() with everything faked and every step accepted."""
    body = b"0123456789"
    kw = dict(
        home=tmp_path / "home",
        gguf_dir=tmp_path / "ggufs",
        confirm=lambda p: True,
        run_cmd=lambda cmd, **k: SimpleNamespace(returncode=0),
        which=lambda c: f"/opt/homebrew/bin/{c}",
        popen=lambda cmd, **k: None,
        http_get=lambda url, timeout=None: SimpleNamespace(status_code=200),
        sleep=lambda s: None,
        client=FakeClient(body),
        log=_quiet,
    )
    kw.update(over)
    return kw


def test_run_happy_path_creates_everything(tmp_path):
    plan = make_plan(pick(), ModelPick("embed", "n/e", "embed.gguf", 10, 0))
    assert bootstrap.run(plan, **_run_kwargs(tmp_path)) == "ok"
    assert (tmp_path / "ggufs" / "tiny.gguf").exists()
    assert (tmp_path / "home" / "start-llamacpp.sh").exists()
    assert (tmp_path / "home" / "llamacpp-presets.ini").exists()


def test_run_aborts_when_install_declined(tmp_path):
    plan = make_plan(pick(), ModelPick("embed", "n/e", "embed.gguf", 10, 0))
    kw = _run_kwargs(tmp_path, which=lambda c: "/x/brew" if c == "brew" else None,
                     confirm=lambda p: False)
    assert bootstrap.run(plan, **kw) == "aborted"
    assert not (tmp_path / "ggufs").exists()


def test_run_advisory_prints_manual_steps(tmp_path):
    plan = make_plan(pick(), ModelPick("embed", "n/e", "embed.gguf", 10, 0))
    lines = []

    def log(*args, **kwargs):
        lines.append(" ".join(str(a) for a in args))

    kw = _run_kwargs(tmp_path, which=lambda c: None, log=log)
    assert bootstrap.run(plan, **kw) == "aborted"
    assert any("brew install llama.cpp" in line for line in lines)
    assert any("curl" in line and "tiny.gguf" in line for line in lines)


def test_run_reports_server_failure(tmp_path):
    def http_get(url, timeout=None):
        raise httpx.ConnectError("down")

    plan = make_plan(pick(), ModelPick("embed", "n/e", "embed.gguf", 10, 0))
    assert bootstrap.run(plan, **_run_kwargs(tmp_path, http_get=http_get)) == "server_failed"


def test_run_skip_install_never_consults_which(tmp_path):
    def which(c):
        raise AssertionError("which must not be called with skip_install")

    plan = make_plan(pick(), ModelPick("embed", "n/e", "embed.gguf", 10, 0))
    kw = _run_kwargs(tmp_path, which=which)
    kw["skip_install"] = True
    assert bootstrap.run(plan, **kw) == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: earlier tests pass; new tests FAIL with `AttributeError: ... 'offer_wired_limit'`

- [ ] **Step 3: Write the implementation**

Append to `src/kultivait/bootstrap.py`:

```python
HEALTH_URL = "http://localhost:8080/v1/models"


def offer_wired_limit(plan: SetupPlan, confirm=ask, run_cmd=subprocess.run, log=print) -> bool:
    """Only offered when plan() flagged the default GPU cap as too tight;
    consent is explicit twice — our confirm, then sudo's password prompt."""
    if not plan.wired_limit_mb:
        return False
    cmd = ["sudo", "sysctl", f"iogpu.wired_limit_mb={plan.wired_limit_mb}"]
    log(
        f"\nYour models want ~{plan.wired_limit_mb} MB of GPU memory but macOS caps it"
        f" at ~{plan.default_gpu_cap_mb} MB by default.\n"
        f"This raises the cap until reboot:  {' '.join(cmd)}"
    )
    if not confirm("Run it now (sudo will ask for your password)?"):
        return False
    return run_cmd(cmd).returncode == 0


def _tail(path: Path, lines: int = 20) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text().splitlines()[-lines:])


def start_server(
    script: Path,
    popen=subprocess.Popen,
    http_get=httpx.get,
    sleep=time.sleep,
    deadline_s: int = 60,
    log=print,
) -> bool:
    """Launch detached, then poll /v1/models — first model load can be slow."""
    log(f"starting llama-server ({script})...")
    popen(["/bin/sh", str(script)], start_new_session=True)
    waited = 0
    while waited < deadline_s:
        try:
            if http_get(HEALTH_URL, timeout=2).status_code == 200:
                log("llama-server is up")
                return True
        except httpx.HTTPError:
            pass
        sleep(2)
        waited += 2
    log(f"llama-server did not answer within {deadline_s}s; last log lines:")
    log(_tail(script.parent / "llamacpp.log"))
    log(f"start it manually and re-run init:  sh {script}")
    return False


def _print_manual_steps(plan: SetupPlan, gguf_dir: Path, log=print) -> None:
    log("manual setup steps:")
    log("  1. install llama.cpp:  brew install llama.cpp")
    log(f"  2. download models into {gguf_dir}:")
    for m in plan.models:
        log(f"       curl -L -o '{gguf_dir / m.filename}' '{m.url()}'")
    log("  3. re-run `kultivait init` — it picks up wherever you left off")


def run(
    plan: SetupPlan,
    *,
    home: "Path | None" = None,
    gguf_dir: "Path | None" = None,
    confirm=ask,
    run_cmd=subprocess.run,
    which=shutil.which,
    popen=subprocess.Popen,
    http_get=httpx.get,
    sleep=time.sleep,
    client=None,
    log=print,
    skip_install: bool = False,
) -> str:
    """Orchestrate the bootstrap: "ok" (server healthy), "aborted" (user
    declined or advisory — continue init as if nothing happened), or
    "server_failed" (don't survey; nothing is listening)."""
    home = home or Path.home() / ".kultivait"
    gguf_dir = gguf_dir or models_dir()
    if not skip_install:
        state = ensure_llamacpp(confirm=confirm, run_cmd=run_cmd, which=which)
        if state == "advisory":
            _print_manual_steps(plan, gguf_dir, log=log)
            return "aborted"
        if state in ("declined", "failed"):
            return "aborted"
    if not download_models(plan, gguf_dir, confirm=confirm, client=client, log=log):
        return "aborted"
    preset, script = write_artifacts(plan, home, gguf_dir)
    log(f"wrote {preset}")
    log(f"wrote {script}")
    offer_wired_limit(plan, confirm=confirm, run_cmd=run_cmd, log=log)
    return "ok" if start_server(script, popen=popen, http_get=http_get, sleep=sleep, log=log) else "server_failed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bootstrap.py -v`
Expected: 28 passed

- [ ] **Step 5: Run the whole suite (nothing else should have moved)**

Run: `uv run pytest`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/kultivait/bootstrap.py tests/test_bootstrap.py
git commit -m "feat: bootstrap orchestrator — wired-limit offer, server start, run()"
```

---

### Task 7: wire it into `cmd_init`

**Files:**
- Modify: `src/kultivait/cli.py`
- Test: `tests/test_cli_init.py` (create)

**Interfaces:**
- Consumes: `hardware.scan()`, `hardware.plan()`, `bootstrap.ask()`, `bootstrap.run()`.
- Produces:
  - `cli._running_runtime() -> "str | None"` — `"ollama" | "llamacpp" | None` (which server actually answers).
  - `cli._stdin_is_tty() -> bool` — trivial wrapper so tests can monkeypatch it.
  - `cli._offer_setup() -> "str | None"` — returns `"llamacpp"` after a successful bootstrap, else `None`; calls `sys.exit(1)` on `"server_failed"`.
  - `kultivait init --no-setup` argparse flag.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_init.py`:

```python
"""cmd_init's zero-to-local seam: offers are gated on TTY/flags/census, and
the survey no longer crashes on a bare machine. All probes monkeypatched."""

import argparse

import httpx
import pytest

import kultivait.cli as cli
from kultivait.hardware import HardwareProfile, SetupPlan

ELIGIBLE = SetupPlan(eligible=True, reason="Apple M3 with 24GB unified RAM")
INELIGIBLE = SetupPlan(eligible=False, reason="needs >=24GB unified RAM; this Mac has 16GB")
PROFILE = HardwareProfile("darwin", "Apple M3", True, 24.0)


@pytest.fixture
def offer_env(monkeypatch):
    """Baseline: interactive TTY, bare machine, eligible hardware."""
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda c: None)
    monkeypatch.setattr(cli.hardware, "scan", lambda: PROFILE)
    monkeypatch.setattr(cli.hardware, "plan", lambda p: ELIGIBLE)
    monkeypatch.setattr(cli.bootstrap, "ask", lambda p: True)
    return monkeypatch


def test_offer_setup_skipped_without_tty(offer_env):
    offer_env.setattr(cli, "_stdin_is_tty", lambda: False)
    offer_env.setattr(cli.hardware, "scan", lambda: 1 / 0)  # must not be reached
    assert cli._offer_setup() is None


def test_offer_setup_defers_to_installed_ollama(offer_env, capsys):
    offer_env.setattr(
        cli.shutil, "which", lambda c: "/usr/local/bin/ollama" if c == "ollama" else None
    )
    assert cli._offer_setup() is None
    assert "ollama serve" in capsys.readouterr().out


def test_offer_setup_explains_ineligible(offer_env, capsys):
    offer_env.setattr(cli.hardware, "plan", lambda p: INELIGIBLE)
    assert cli._offer_setup() is None
    assert "16GB" in capsys.readouterr().out


def test_offer_setup_declined(offer_env):
    offer_env.setattr(cli.bootstrap, "ask", lambda p: False)
    offer_env.setattr(cli.bootstrap, "run", lambda *a, **k: 1 / 0)  # must not run
    assert cli._offer_setup() is None


def test_offer_setup_bootstraps_and_reports_llamacpp(offer_env):
    seen = {}

    def fake_run(plan, **kwargs):
        seen["plan"], seen["kwargs"] = plan, kwargs
        return "ok"

    offer_env.setattr(cli.bootstrap, "run", fake_run)
    assert cli._offer_setup() == "llamacpp"
    assert seen["plan"] is ELIGIBLE
    assert seen["kwargs"]["skip_install"] is False


def test_offer_setup_skips_install_when_llamacpp_present(offer_env):
    offer_env.setattr(
        cli.shutil, "which", lambda c: "/opt/homebrew/bin/llama-server" if c == "llama-server" else None
    )
    seen = {}

    def fake_run(plan, **kwargs):
        seen["kwargs"] = kwargs
        return "ok"

    offer_env.setattr(cli.bootstrap, "run", fake_run)
    assert cli._offer_setup() == "llamacpp"
    assert seen["kwargs"]["skip_install"] is True


def test_offer_setup_exits_when_server_fails(offer_env):
    offer_env.setattr(cli.bootstrap, "run", lambda *a, **k: "server_failed")
    with pytest.raises(SystemExit):
        cli._offer_setup()


def test_cmd_init_survives_bare_machine(monkeypatch, tmp_path, capsys):
    """No runtime anywhere: --no-setup init writes a virtual-tier config
    instead of crashing with a connection error."""
    monkeypatch.setattr(cli, "_running_runtime", lambda: None)
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)

    def refuse(runtime):
        raise httpx.ConnectError("nothing listening")

    monkeypatch.setattr(cli, "_survey_local", refuse)
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    cli.cmd_init(argparse.Namespace(no_setup=True))
    text = (tmp_path / "config.toml").read_text()
    assert 'kind = "virtual"' in text


def test_cmd_init_no_setup_never_offers(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_running_runtime", lambda: None)
    monkeypatch.setattr(cli, "_offer_setup", lambda: 1 / 0)  # must not be reached
    monkeypatch.setattr(cli, "_available_clis", lambda: [])
    monkeypatch.delenv("KULTIVAIT_RUNTIME", raising=False)
    monkeypatch.setattr(cli, "_survey_local", lambda r: ([], {}))
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.toml")
    cli.cmd_init(argparse.Namespace(no_setup=True))  # would ZeroDivisionError if offered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_init.py -v`
Expected: FAIL — `AttributeError: module 'kultivait.cli' has no attribute 'hardware'` (and friends)

- [ ] **Step 3: Modify `src/kultivait/cli.py`**

3a. Add imports after the existing `from kultivait...` imports (keep alphabetical-ish grouping):

```python
import kultivait.bootstrap as bootstrap
import kultivait.hardware as hardware
```

3b. Replace `_detect_runtime` (currently `cli.py:136-146`) with a split version — existing behavior preserved, running-check reusable:

```python
def _running_runtime() -> "str | None":
    """Which local server actually answers right now, if any."""
    if _reachable(f"{OLLAMA_URL}/api/tags"):
        return "ollama"
    if _reachable(f"{LLAMACPP_URL}/v1/models"):
        return "llamacpp"
    return None


def _detect_runtime() -> str:
    """Prefer whichever local server is actually running; if both, ollama
    (the eval-proven setup). KULTIVAIT_RUNTIME overrides."""
    return os.environ.get("KULTIVAIT_RUNTIME") or _running_runtime() or "ollama"
```

3c. Add the offer seam (place it directly above `cmd_init`):

```python
def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _offer_setup() -> "str | None":
    """Zero-to-local: nothing is running, so scan the hardware and offer to
    bootstrap llama.cpp. Returns "llamacpp" once a healthy server is up."""
    if not _stdin_is_tty():
        return None
    if shutil.which("ollama"):
        print("ollama is installed but not running — start it (ollama serve), then re-run `kultivait init`.")
        return None
    setup_plan = hardware.plan(hardware.scan())
    have_llamacpp = bool(shutil.which("llama-server"))
    if not setup_plan.eligible:
        print(f"local-model setup not offered: {setup_plan.reason}")
        if have_llamacpp:
            print("llama-server is installed — start it and re-run `kultivait init`.")
        else:
            print("cloud CLIs (claude/agy/gemini) still route; local tiers stay virtual.")
        return None
    print(f"\nthis machine can grow a local garden: {setup_plan.reason}")
    if not bootstrap.ask("Set up llama.cpp with tuned defaults now?"):
        return None
    outcome = bootstrap.run(setup_plan, skip_install=have_llamacpp)
    if outcome == "server_failed":
        sys.exit(1)
    return "llamacpp" if outcome == "ok" else None
```

3d. Replace the first two lines of `cmd_init` (currently `runtime = _detect_runtime()` then `models, sizes = _survey_local(runtime)` at `cli.py:273-275`) with:

```python
def cmd_init(args: argparse.Namespace) -> None:
    running = _running_runtime()
    if running is None and not args.no_setup:
        running = _offer_setup()
    runtime = os.environ.get("KULTIVAIT_RUNTIME") or running or "ollama"
    try:
        models, sizes = _survey_local(runtime)
    except httpx.HTTPError:
        models, sizes = [], {}  # bare machine: virtual-tier config, not a traceback
```

(the rest of `cmd_init` — `clis = _available_clis()` onward — is unchanged.)

3e. Add the flag to the `init` subparser in `main()` (currently `cli.py:416-417`):

```python
    init = sub.add_parser("init", help="survey this machine and write config")
    init.add_argument(
        "--no-setup", action="store_true", help="never offer to install or download anything"
    )
    init.set_defaults(func=cmd_init)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_init.py tests/test_cli_runtime.py -v`
Expected: all pass (the `_detect_runtime` refactor must keep the three existing runtime tests green)

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add src/kultivait/cli.py tests/test_cli_init.py
git commit -m "feat: kultivait init offers zero-to-local llama.cpp bootstrap on capable Macs"
```

---

### Task 8: docs + final verification

**Files:**
- Modify: `README.md` (Requirements section, `README.md:136-145` area)
- Modify: `CLAUDE.md` (Commands/requirements note)

**Interfaces:**
- Consumes: the behavior shipped in Tasks 1–7. No code.

- [ ] **Step 1: Add the README subsection**

In `README.md`, immediately after the Requirements bullet list (after the line `- optional: `claude` / `agy` / `gemini` CLIs on PATH for cloud tiers`) and before `### Using with llama.cpp instead of ollama`, insert:

```markdown
### Zero to local: `kultivait init` on a Mac

On an Apple Silicon Mac with at least 24GB of unified memory and no local
runtime installed, `kultivait init` offers to do the whole setup itself:
install llama.cpp via Homebrew, download models sized to your RAM (plus the
nomic-embed GGUF), write a tuned launch script
(`~/.kultivait/start-llamacpp.sh`), and start the server — asking before
every step that touches your machine. Re-running `init` is safe: finished
steps are skipped and interrupted downloads resume. Opt out with
`kultivait init --no-setup` (offers are also skipped when stdin is not a
TTY).
```

- [ ] **Step 2: Update CLAUDE.md's stale requirement line**

In `CLAUDE.md`, the paragraph beginning `Requires a local `ollama`` — append one sentence so it reads correctly with the new flow:

```markdown
Requires a local `ollama` (with a model pulled) or `llama-server` in router mode reachable at their default ports for anything that embeds or generates (`serve`, `route`, `init`, `prune`, `escalations --brief`); pure unit tests (router, config, ledger, escalations, gates logic) don't need either. On a bare Apple Silicon Mac (≥24GB), `kultivait init` can bootstrap llama.cpp itself — hardware sizing lives in `src/kultivait/hardware.py`, the confirmed install/download/launch steps in `src/kultivait/bootstrap.py`.
```

- [ ] **Step 3: Full-suite verification**

Run: `uv run pytest`
Expected: all passing

If `llama-server` happens to be installed on the implementing machine, sanity-check the generated flag spelling: `llama-server --help 2>&1 | grep -E "flash-attn|-fa"` — expect it to accept `-fa on` (on/off/auto form). If only the bare `--flash-attn` boolean form is accepted (very old build), change the flags tuple in `hardware.plan()` to use `("--flash-attn",)` instead of `("-fa", "on")` and update `test_server_flags_carry_tuning_and_ctx` to match. If llama-server is not installed, skip this check — brew installs current releases where `-fa on` is correct.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document zero-to-local init bootstrap"
```
