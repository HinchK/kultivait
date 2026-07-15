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
