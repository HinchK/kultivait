"""Shadow pass: post-response comparison of a gate-passing distillate against
the incumbent on contested traffic (ADR 0017).

The shadow runs AFTER the live response completes — fire-and-forget into a
worker thread with total exception isolation: a shadow crash never touches
serving, and outcomes land in ``~/.kultivait/shadow.jsonl`` — outside the
main ledger by design, so shadow rows never pollute toll stats, routing
analytics, or the harvest's cost lenses. Cutover-readiness derives from the
log: agreement >= 90% over >= 30 shadowed contested requests AND zero
anomalies (parse failures, dangerous local verdicts on escalatory prompts);
the human flips the [distill] model knob — never automatic.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from kultivait.distill.eval import derive_verdict
from kultivait.preprocessor import extract_json

CUTOVER_AGREEMENT = 0.90
CUTOVER_MIN_N = 30

_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="kultivait-shadow"
)


@dataclass(frozen=True)
class ShadowRecord:
    ts: float
    fingerprint: str
    prompt_hash: str
    incumbent: dict
    shadow: dict
    agree: bool


def _default_log_path() -> Path:
    return Path.home() / ".kultivait" / "shadow.jsonl"


def append_shadow_log(record: ShadowRecord, path: "Path | None" = None) -> None:
    p = Path(path) if path else _default_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")


def read_shadow_log(path: "Path | None" = None) -> list:
    p = Path(path) if path else _default_log_path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def compute_cutover_readiness(rows: list) -> dict:
    """ADR 0017 cutover criteria over the shadow log (records or dicts)."""
    norm = [asdict(r) if isinstance(r, ShadowRecord) else r for r in rows]
    rows = norm
    n = len(rows)
    reasons: list[str] = []
    if n < CUTOVER_MIN_N:
        reasons.append(f"n < {CUTOVER_MIN_N}")
    agreeing = sum(1 for r in rows if r.get("agree"))
    agreement = agreeing / n if n else 0.0
    if n and agreement < CUTOVER_AGREEMENT:
        reasons.append(f"agreement {agreement:.2f} < {CUTOVER_AGREEMENT}")
    anomalies = sum(
        1 for r in rows
        if not r.get("shadow", {}).get("parse_ok", False)
        or r.get("shadow", {}).get("dangerous", False)
    )
    if anomalies:
        reasons.append(f"{anomalies} anomalies (parse failures / dangerous shadows)")
    return {
        "n": n,
        "agreement": round(agreement, 4),
        "anomalies": anomalies,
        "cutover_ready": not reasons,
        "reasons": reasons,
        "criteria": {"agreement": CUTOVER_AGREEMENT, "min_n": CUTOVER_MIN_N,
                     "anomalies_allowed": 0},
    }


def run_shadow_pass(
    prompt: str,
    fingerprint: str,
    *,
    incumbent_model: str,
    incumbent_verdict: str,
    incumbent_max_fit: float,
    incumbent_latency_s: float,
    shadow_model: str,
    generate,
) -> ShadowRecord:
    """One shadow comparison: same prompt, shadow model, never blocking."""
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    t0 = time.monotonic()
    parse_ok, verdict, max_fit = False, None, 0.0
    dangerous = False
    try:
        out = generate(shadow_model, prompt)
        raw = out[0] if isinstance(out, tuple) else str(out)
        latency = float(out[1]) if isinstance(out, tuple) else round(time.monotonic() - t0, 2)
        contract, _err = extract_json(raw)
        if contract is not None:
            parse_ok = True
            targets = contract.get("judge", {}).get("targets", [])
            max_fit = max((float(t.get("fit", 0.0)) for t in targets if isinstance(t, dict)),
                          default=0.0)
            verdict = derive_verdict(max_fit)
            # dangerous: the incumbent routed frontier; the shadow would keep it local
            dangerous = verdict == "local" and incumbent_verdict == "frontier"
    except Exception:  # noqa: BLE001 - total isolation; failure is an anomaly row
        latency = round(time.monotonic() - t0, 2)

    return ShadowRecord(
        ts=time.time(), fingerprint=fingerprint, prompt_hash=prompt_hash,
        incumbent={"model": incumbent_model, "verdict": incumbent_verdict,
                   "max_fit": incumbent_max_fit, "latency_s": incumbent_latency_s,
                   "parse_ok": True},
        shadow={"model": shadow_model, "verdict": verdict, "max_fit": max_fit,
                "latency_s": latency, "parse_ok": parse_ok, "dangerous": dangerous},
        agree=parse_ok and verdict == incumbent_verdict,
    )


def schedule_shadow_pass(
    prompt: str,
    fingerprint: str,
    *,
    incumbent_model: str,
    incumbent_verdict: str,
    incumbent_max_fit: float,
    incumbent_latency_s: float,
    shadow_model: str,
    generate,
    log_path: "Path | None" = None,
) -> None:
    """Fire-and-forget: submit the pass to the worker; never raise, never block."""

    def _work():
        try:
            record = run_shadow_pass(
                prompt, fingerprint, incumbent_model=incumbent_model,
                incumbent_verdict=incumbent_verdict,
                incumbent_max_fit=incumbent_max_fit,
                incumbent_latency_s=incumbent_latency_s,
                shadow_model=shadow_model, generate=generate,
            )
            append_shadow_log(record, log_path)
        except Exception:  # noqa: BLE001 - a shadow crash never touches serving
            pass

    try:
        _EXECUTOR.submit(_work)
    except RuntimeError:  # executor shut down mid-flight
        pass


def shadow_after_response(
    *,
    shadow_mode: str,
    shadow_model: str,
    prompt: str,
    fingerprint: str,
    incumbent_model: str,
    incumbent_verdict: str,
    incumbent_max_fit: float,
    incumbent_latency_s: float,
    generate,
    log_path: "Path | None" = None,
    sample_rate: float = 1.0,
) -> None:
    """The post-response hook the contested path calls: schedules the shadow
    only when mode=on and a shadow model is configured (sampled)."""
    if shadow_mode != "on" or not shadow_model:
        return
    if sample_rate <= 0.0:
        return
    import random

    if random.random() > sample_rate:
        return
    schedule_shadow_pass(
        prompt, fingerprint, incumbent_model=incumbent_model,
        incumbent_verdict=incumbent_verdict, incumbent_max_fit=incumbent_max_fit,
        incumbent_latency_s=incumbent_latency_s, shadow_model=shadow_model,
        generate=generate, log_path=log_path,
    )


class DistillSeat:
    """The live preprocessor seat (ADR 0017): the model resolves per call, so
    a seat update swaps models on the next request with no restart."""

    def __init__(self, model: str, shadow_model: str, shadow_mode: str,
                 shadow_sample_rate: float = 1.0):
        self.model = model
        self.shadow_model = shadow_model
        self.shadow_mode = shadow_mode
        self.shadow_sample_rate = shadow_sample_rate

    @classmethod
    def from_config(cls, config) -> "DistillSeat":
        d = config.distill
        return cls(d.model, d.shadow_model, d.shadow_mode, d.shadow_sample_rate)

    def set_model(self, model: str) -> None:
        self.model = model

    def shadow_on(self) -> bool:
        return self.shadow_mode == "on" and bool(self.shadow_model)


def _percentile(values: list, p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(p * (len(s) - 1))))
    return s[k]


def shadow_summary(log_path: "Path | None" = None) -> dict:
    """S1 (#101): the enriched read — latency deltas, parse validity, the
    calibration-correction read, and the #73 decomposed readiness."""
    rows = read_shadow_log(log_path)
    readiness = compute_cutover_readiness(rows)
    models = {
        "incumbent": sorted({r.get("incumbent", {}).get("model") for r in rows
                             if r.get("incumbent", {}).get("model")}),
        "shadow": sorted({r.get("shadow", {}).get("model") for r in rows
                          if r.get("shadow", {}).get("model")}),
    }

    # latency deltas (shadow - incumbent per record; negative = shadow faster)
    inc_lat = [r.get("incumbent", {}).get("latency_s", 0) for r in rows]
    sh_lat = [r.get("shadow", {}).get("latency_s", 0) for r in rows]
    deltas = [s - i for i, s in zip(inc_lat, sh_lat)] if rows else []
    latency = {
        "incumbent_p50_s": round(_percentile(inc_lat, 0.5), 2),
        "incumbent_p90_s": round(_percentile(inc_lat, 0.9), 2),
        "shadow_p50_s": round(_percentile(sh_lat, 0.5), 2),
        "shadow_p90_s": round(_percentile(sh_lat, 0.9), 2),
        "delta_p50_s": round(_percentile(deltas, 0.5), 2) if deltas else 0.0,
        "delta_p90_s": round(_percentile(deltas, 0.9), 2) if deltas else 0.0,
    }

    # parse validity
    parse_ok = sum(1 for r in rows if r.get("shadow", {}).get("parse_ok"))
    parse_validity = round(parse_ok / len(rows), 4) if rows else 0.0

    # calibration divergence: the verdict-pair distribution (#73's expected
    # divergence — shadow contested where incumbent says frontier = correction)
    divergence: dict = {}
    corrections = 0
    for r in rows:
        iv = r.get("incumbent", {}).get("verdict") or "?"
        sv = r.get("shadow", {}).get("verdict") or "?"
        pair = f"inc:{iv}->shadow:{sv}"
        divergence[pair] = divergence.get(pair, 0) + 1
        if iv == "frontier" and sv == "contested":
            corrections += 1
    calibration = {
        "verdict_pairs": divergence,
        "calibration_corrections": corrections,
        "correction_rate": round(corrections / len(rows), 4) if rows else 0.0,
    }

    # the #73 decomposed readiness arms
    non_contested = [r for r in rows
                     if r.get("incumbent", {}).get("verdict") in ("local", "frontier")]
    stability_agree = (sum(1 for r in non_contested if r.get("agree"))
                       / len(non_contested)) if non_contested else 0.0
    shadow_contested = sum(1 for r in rows
                           if r.get("shadow", {}).get("verdict") == "contested")
    repopulation = round(shadow_contested / len(rows), 4) if rows else 0.0
    readiness_arms = {
        "stability_non_contested_ge_90": {
            "value": round(stability_agree, 4), "bar": 0.90,
            "pass": stability_agree >= 0.90},
        "repopulation_band_5_to_25": {
            "value": repopulation, "bar": "5%-25%",
            "pass": 0.05 <= repopulation <= 0.25},
        "health_zero_anomalies": {
            "value": readiness.get("anomalies", 0), "bar": 0,
            "pass": readiness.get("anomalies", 0) == 0},
        "sample_n_ge_30": {
            "value": readiness.get("n", 0), "bar": 30,
            "pass": readiness.get("n", 0) >= 30},
    }

    return {**readiness, "models": models,
            "latency": latency,
            "parse_validity": parse_validity,
            "calibration": calibration,
            "readiness_arms": readiness_arms,
            "instruction": ("cutover is the human flip: set [distill] model to the "
                            "shadow candidate; rollback = revert the knob")}
