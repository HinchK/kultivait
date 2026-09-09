"""Local-compute energy estimation (ADR 0020).

Coefficients are measured, versioned, and labeled as estimates everywhere.
The embedded table mirrors experiments/energy_measurement/coefficients.toml
(energy-v1-20260909); config may override VALUES, never provenance.
"""

import re
import tomllib
from pathlib import Path

TABLE_VERSION = "energy-v1-20260909"

# class -> (prefill Wh per 1K tokens, decode Wh per 1K tokens)
CLASSES: dict[str, tuple[float, float]] = {
    "1.5b": (0.00010, 0.03784),
    "3b": (0.00007, 0.07214),
    "4b": (0.00341, 0.13042),
    "8b": (0.00060, 0.19242),
    "14b": (0.00074, 0.38760),
}
DEFAULT_CLASS = "8b"

_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b", re.IGNORECASE)


def _load_overrides(config_path: Path | None) -> dict:
    if config_path is None or not Path(config_path).is_file():
        return {}
    try:
        return tomllib.loads(Path(config_path).read_text()).get("energy", {})
    except Exception:
        return {}


def active_version(overrides: dict | None = None) -> str:
    """The version tag stamped on records (override-aware)."""
    if overrides and overrides.get("table_version_override"):
        return str(overrides["table_version_override"])
    return TABLE_VERSION


def resolve_class(model_name: str, *, overrides: dict | None = None,
                  class_overrides: dict | None = None) -> str:
    """Model -> parameter-class bucket: explicit tier override, then a
    parameter-count parse against bucket midpoints, then the default."""
    if class_overrides and model_name in class_overrides:
        return str(class_overrides[model_name])
    default = (overrides or {}).get("default_class", DEFAULT_CLASS)
    buckets = {k: float(k.replace("b", "")) for k in CLASSES}
    best, best_gap = None, None
    for match in _PARAM_RE.finditer(model_name or ""):
        params = float(match.group(1))
        for name, midpoint in buckets.items():
            if midpoint <= 0.9 * params or midpoint >= 1.6 * params:
                continue  # implausible bucket for this count
            gap = abs(midpoint - params)
            if best_gap is None or gap < best_gap:
                best, best_gap = name, gap
        if best:
            break  # first plausible parameter count in the name wins
    return best or str(default)


def _coefficient(cls: str, overrides: dict | None = None) -> tuple[float, float]:
    table = dict(CLASSES)
    for row in (overrides or {}).get("coefficient_overrides", []) or []:
        if isinstance(row, dict) and row.get("class") in table and "decode" in row:
            table[str(row["class"])] = (
                float(row.get("prefill", table[str(row["class"])][0])),
                float(row["decode"]),
            )
    return table.get(cls, table[DEFAULT_CLASS])


def dispatch_estimate(
    *, is_local: bool, model: str, tokens_in: int, tokens_out: int,
    overrides: dict | None = None, class_overrides: dict | None = None,
) -> tuple[float, str]:
    """(est_wh, energy_model) for a dispatch record. Non-local dispatches
    carry 0.0 — their energy is not ours to claim (ADR 0020)."""
    version = active_version(overrides)
    if not is_local:
        return 0.0, version
    prefill, decode = _coefficient(
        resolve_class(model, overrides=overrides, class_overrides=class_overrides),
        overrides,
    )
    est_wh = (tokens_in * prefill + tokens_out * decode) / 1000.0
    return round(est_wh, 6), version


def sig2(value: float) -> str:
    """Two-significant-figure display (invariant 2)."""
    return f"{value:.2g}"
