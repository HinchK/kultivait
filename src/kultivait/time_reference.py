"""Frontier-latency reference table (ADR 0024 / the #215 pin).

The time yardstick: versioned, season-pinned medians of frontier first-token
and total latency per prompt-token band, applied at HARVEST time only.
Time-never-ranks: this table is observability, never a routing input — the
length rule is the sole time-derived routing policy and lives in server.py.
The embedded values mirror the committed probe provenance in
experiments/latency_probe/; config may override VALUES, never provenance.
"""

import tomllib
from pathlib import Path

TABLE_VERSION = "time-v1-20260913-openrouter/claude-sonnet-5"

# prompt-token bands: lower-inclusive, upper-exclusive (2048 -> "2-8k")
BANDS: tuple[tuple[str, int, "int | None"], ...] = (
    ("0-2k", 0, 2048),
    ("2-8k", 2048, 8192),
    ("8k+", 8192, None),
)

# band -> measured frontier medians (ms), from experiments/latency_probe/
REFERENCE_MEDIANS: dict[str, dict[str, int]] = {}


def _load_overrides(config_path: Path | None) -> dict:
    if config_path is None or not Path(config_path).is_file():
        return {}
    try:
        return tomllib.loads(Path(config_path).read_text()).get("time_reference", {})
    except Exception:
        return {}


def active_version(overrides: dict | None = None) -> str:
    if overrides and overrides.get("table_version_override"):
        return str(overrides["table_version_override"])
    return TABLE_VERSION


def band_for(tokens_in: int) -> str:
    for name, lo, hi in BANDS:
        if tokens_in >= lo and (hi is None or tokens_in < hi):
            return name
    return BANDS[-1][0]


def medians(overrides: dict | None = None) -> dict[str, dict[str, int]]:
    """The active table: committed values, config may override per band."""
    table = {band: dict(vals) for band, vals in REFERENCE_MEDIANS.items()}
    for row in (overrides or {}).get("band_overrides", []) or []:
        if isinstance(row, dict) and row.get("band"):
            band = str(row["band"])
            if band in table:
                table[band] = {
                    "first_token_ms": int(row.get("first_token_ms", table[band]["first_token_ms"])),
                    "total_ms": int(row.get("total_ms", table[band]["total_ms"])),
                }
            elif {"first_token_ms", "total_ms"} <= row.keys():
                table[band] = {
                    "first_token_ms": int(row["first_token_ms"]),
                    "total_ms": int(row["total_ms"]),
                }
    return table


def available(overrides: dict | None = None) -> bool:
    """A yardstick exists only when every band carries measured values."""
    return bool(medians(overrides)) and all(
        band in medians(overrides) for band, _, _ in BANDS
    )
