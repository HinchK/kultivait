"""Append-only JSONL ledger of routing decisions and the savings they earned."""

import json
import time
from pathlib import Path


class Ledger:
    def __init__(self, path: Path, baseline_in: float = 3.0, baseline_out: float = 15.0):
        self._path = Path(path)
        self._baseline_in = baseline_in  # USD per million input tokens at a frontier model
        self._baseline_out = baseline_out  # USD per million output tokens

    def record(
        self,
        *,
        tier: str,
        local: bool,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        notional_usd: float | None = None,
        fingerprint: str | None = None,
        **extra,
    ) -> None:
        """Extra keyword fields (routing decision metadata, truncation flags,
        prompt snippets) are stored verbatim — the ledger is the analysis
        substrate, so silent failure modes must leave a trace here."""
        if notional_usd is None:
            notional_usd = cost_usd
        entry = {
            "ts": time.time(),
            "tier": tier,
            "local": local,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "notional_usd": notional_usd,
        }
        if fingerprint is not None:
            entry["fingerprint"] = fingerprint
        entry.update(extra)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def harvest(self) -> dict:
        entries = []
        if self._path.exists():
            with self._path.open() as f:
                entries = [json.loads(line) for line in f if line.strip()]
        tokens_in = sum(e["tokens_in"] for e in entries)
        tokens_out = sum(e["tokens_out"] for e in entries)
        metered_spent = sum(e.get("cost_usd", 0.0) for e in entries)
        notional_spent = sum(e.get("notional_usd", e.get("cost_usd", 0.0)) for e in entries)
        baseline = (tokens_in * self._baseline_in + tokens_out * self._baseline_out) / 1e6
        # fallback_reason is current; tool_fallback is the pre-config legacy field
        escalations = [e for e in entries if e.get("fallback_reason") or e.get("tool_fallback")]

        tolls_fired = sum(1 for e in entries if e.get("toll") in ("fired", "answered", "expired"))
        tolls_answered = sum(1 for e in entries if e.get("toll") == "answered")
        tolls_expired = sum(1 for e in entries if e.get("toll") == "expired")
        tolls_skipped = sum(1 for e in entries if e.get("toll") == "skipped")

        route_choices: dict[str, int] = {}
        route_choice_groups = {
            "human:local": 0,
            "human:frontier": 0,
            "auto:local": 0,
            "auto:frontier": 0,
        }
        for e in entries:
            rc = e.get("route_choice")
            if rc:
                route_choices[rc] = route_choices.get(rc, 0) + 1
                if rc == "human:local":
                    route_choice_groups["human:local"] += 1
                elif rc.startswith("human:frontier"):
                    route_choice_groups["human:frontier"] += 1
                elif rc == "auto:local":
                    route_choice_groups["auto:local"] += 1
                elif rc.startswith("auto:frontier"):
                    route_choice_groups["auto:frontier"] += 1

        preprocess_marks = {
            "ok": sum(1 for e in entries if e.get("preprocess_mark") == "ok"),
            "skipped": sum(1 for e in entries if e.get("preprocess_mark") == "skipped"),
            "timeout": sum(1 for e in entries if e.get("preprocess_mark") == "preprocess_timeout"),
            "fail": sum(1 for e in entries if e.get("preprocess_mark") == "preprocess_fail"),
        }

        toll_rate = (tolls_fired / len(entries)) if entries else 0.0

        return {
            "prompts": len(entries),
            "local_prompts": sum(1 for e in entries if e["local"]),
            "tokens_local": sum(e["tokens_in"] + e["tokens_out"] for e in entries if e["local"]),
            "spent_usd": notional_spent,
            "notional_spent_usd": notional_spent,
            "metered_spent_usd": metered_spent,
            "baseline_usd": baseline,
            "saved_usd": baseline - notional_spent,
            "metered_saved_usd": baseline - metered_spent,
            "escalations": {
                "count": len(escalations),
                "recent": [
                    {
                        "requested": e.get("requested_tier"),
                        "served": e["tier"],
                        "snippet": e.get("snippet", ""),
                    }
                    for e in escalations[-5:]
                ],
            },
            "truncated_inputs": sum(1 for e in entries if e.get("truncated")),
            "toll_activity": {
                "fired": tolls_fired,
                "answered": tolls_answered,
                "expired": tolls_expired,
                "skipped": tolls_skipped,
                "toll_rate": toll_rate,
                "route_choices": route_choices,
                "route_choice_groups": route_choice_groups,
                "preprocess_marks": preprocess_marks,
            },
        }
