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


def test_all_pinned_models_carry_sha256():
    picks = (
        hw.EMBED_PICK, hw.QWEN3_4B, hw.QWEN3_8B,
        hw.QWEN3_14B, hw.QWEN3_32B_Q4, hw.QWEN3_32B_Q5,
    )
    for pick in picks:
        assert len(pick.sha256) == 64
        assert set(pick.sha256) <= set("0123456789abcdef")
