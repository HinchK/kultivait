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
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_ttl: str = "",
        cache_price_in: float = 0.0,
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
        if cache_read_tokens or cache_write_tokens:
            entry["cache_read_tokens"] = cache_read_tokens
            entry["cache_write_tokens"] = cache_write_tokens
            entry["cache_ttl"] = cache_ttl or "5m"
            if cache_price_in:
                entry["cache_price_in"] = cache_price_in
        entry.update(extra)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def _cache_section(self, entries: list) -> dict:
        """Cache economics per the ADR 0005 amendment: kept-via-cache is the
        third line (routing / metered / caching stay orthogonal). Net savings
        price the read discount (reads*0.9) against the write premium
        (writes*(mult-1)); the entry's effective input price rides the record.
        """
        cached = [e for e in entries if e.get("cache_read_tokens") or e.get("cache_write_tokens")]
        mult = {"5m": 1.25, "1h": 2.0}
        cohorts: dict = {}
        tot_reads = tot_writes = 0
        tot_input = 0
        kept = 0.0
        for e in cached:
            reads = int(e.get("cache_read_tokens", 0))
            writes = int(e.get("cache_write_tokens", 0))
            price = float(e.get("cache_price_in", 0.0))
            ttl = e.get("cache_ttl", "5m")
            m = mult.get(ttl, 1.25)
            entry_kept = (reads * 0.9 * price - writes * (m - 1.0) * price) / 1e6
            kept += entry_kept
            tot_reads += reads
            tot_writes += writes
            tot_input += int(e.get("tokens_in", 0))
            c = cohorts.setdefault(ttl, {"dispatches": 0, "kept_via_cache_usd": 0.0})
            c["dispatches"] += 1
            c["kept_via_cache_usd"] += entry_kept
        return {
            "dispatches": len(cached),
            "kept_via_cache_usd": round(kept, 6),
            "cache_hit_rate": round(tot_reads / tot_input, 4) if tot_input else 0.0,
            "cache_reads_per_write": round(tot_reads / tot_writes, 2) if tot_writes else 0.0,
            "cache_ttl_cohorts": {k: {"dispatches": v["dispatches"],
                                      "kept_via_cache_usd": round(v["kept_via_cache_usd"], 6)}
                                  for k, v in cohorts.items()},
        }
    def _by_generation(self, prompt_entries: list) -> dict:
        """S3 (#103): per-distillate-generation slicing on preprocess_model —
        untagged/legacy entries group under 'legacy/incumbent'."""
        gens: dict = {}
        for e in prompt_entries:
            gen = e.get("preprocess_model") or "legacy/incumbent"
            g = gens.setdefault(gen, {"requests": 0, "saved_usd": 0.0,
                                      "cache": {"dispatches": 0, "kept_via_cache_usd": 0.0,
                                                "cache_read_tokens": 0, "tokens_in": 0}})
            g["requests"] += 1
            g["saved_usd"] += max(0.0, e.get("notional_usd", e.get("cost_usd", 0.0))
                                  - e.get("cost_usd", 0.0))
            if e.get("cache_read_tokens") or e.get("cache_write_tokens"):
                g["cache"]["dispatches"] += 1
                g["cache"]["kept_via_cache_usd"] += (
                    (e.get("cache_read_tokens", 0) * 0.9 * e.get("cache_price_in", 0.0)
                     - e.get("cache_write_tokens", 0)
                     * ({"5m": 1.25, "1h": 2.0}.get(e.get("cache_ttl", "5m"), 1.25) - 1.0)
                     * e.get("cache_price_in", 0.0)) / 1e6)
                g["cache"]["cache_read_tokens"] += e.get("cache_read_tokens", 0)
                g["cache"]["tokens_in"] += e.get("tokens_in", 0)
        for gen, g in gens.items():
            g["saved_usd"] = round(g["saved_usd"], 4)
            c = g["cache"]
            c["kept_via_cache_usd"] = round(c["kept_via_cache_usd"], 6)
            c["cache_hit_rate"] = (round(c["cache_read_tokens"] / c["tokens_in"], 4)
                                   if c["tokens_in"] else 0.0)
        return gens

    def harvest(self) -> dict:
        entries = []
        if self._path.exists():
            with self._path.open() as f:
                entries = [json.loads(line) for line in f if line.strip()]
        prompt_entries = [e for e in entries if e.get("tag") != "counterfactual" and e.get("tier") != "counterfactual"]
        tokens_in = sum(e["tokens_in"] for e in prompt_entries)
        tokens_out = sum(e["tokens_out"] for e in prompt_entries)
        metered_spent = sum(e.get("cost_usd", 0.0) for e in prompt_entries)
        notional_spent = sum(e.get("notional_usd", e.get("cost_usd", 0.0)) for e in prompt_entries)
        baseline = (tokens_in * self._baseline_in + tokens_out * self._baseline_out) / 1e6
        # fallback_reason is current; tool_fallback is the pre-config legacy field
        escalations = [e for e in prompt_entries if e.get("fallback_reason") or e.get("tool_fallback")]

        tolls_fired = sum(1 for e in prompt_entries if e.get("toll") in ("fired", "answered", "expired"))
        tolls_answered = sum(1 for e in prompt_entries if e.get("toll") == "answered")
        tolls_expired = sum(1 for e in prompt_entries if e.get("toll") == "expired")
        tolls_skipped = sum(1 for e in prompt_entries if e.get("toll") == "skipped")
        counterfactuals_count = sum(1 for e in entries if e.get("tag") == "counterfactual" or e.get("counterfactual_choice"))

        route_choices: dict[str, int] = {}
        route_choice_groups = {
            "human:local": 0,
            "human:frontier": 0,
            "auto:local": 0,
            "auto:frontier": 0,
        }
        for e in prompt_entries:
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
            "ok": sum(1 for e in prompt_entries if e.get("preprocess_mark") == "ok"),
            "skipped": sum(1 for e in prompt_entries if e.get("preprocess_mark") == "skipped"),
            "timeout": sum(1 for e in prompt_entries if e.get("preprocess_mark") == "preprocess_timeout"),
            "fail": sum(1 for e in prompt_entries if e.get("preprocess_mark") == "preprocess_fail"),
        }

        toll_rate = (tolls_fired / len(prompt_entries)) if prompt_entries else 0.0

        cache = self._cache_section(prompt_entries)
        by_generation = self._by_generation(prompt_entries)

        return {
            "cache": cache,
            "by_generation": by_generation,
            "prompts": len(prompt_entries),
            "local_prompts": sum(1 for e in prompt_entries if e.get("local")),
            "tokens_local": sum(e["tokens_in"] + e["tokens_out"] for e in prompt_entries if e.get("local")),
            "spent_usd": notional_spent,
            "notional_spent_usd": notional_spent,
            "metered_spent_usd": metered_spent,
            "baseline_usd": baseline,
            "saved_usd": baseline - notional_spent,
            "metered_saved_usd": baseline - metered_spent,
            "counterfactuals": counterfactuals_count,
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
                "counterfactuals": counterfactuals_count,
                "toll_rate": toll_rate,
                "route_choices": route_choices,
                "route_choice_groups": route_choice_groups,
                "preprocess_marks": preprocess_marks,
            },
        }
