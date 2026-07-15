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
