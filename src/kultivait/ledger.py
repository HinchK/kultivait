"""Append-only JSONL ledger of routing decisions and the savings they earned."""

import json
import time
from pathlib import Path


class Ledger:
    def __init__(self, path: Path, baseline_in: float = 3.0, baseline_out: float = 15.0):
        self._path = Path(path)
        self._baseline_in = baseline_in  # USD per million input tokens at a frontier model
        self._baseline_out = baseline_out  # USD per million output tokens
        self._row_count: "int | None" = None

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
        est_wh: float = 0.0,
        energy_model: str = "",
        latency_s: float | None = None,
        first_token_ms: "int | None" = None,
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
        # ADR 0020: every dispatch record carries the energy estimate and its
        # coefficient-table tag; latency is forward-looking substrate.
        entry["est_wh"] = est_wh
        if energy_model:
            entry["energy_model"] = energy_model
        if latency_s is not None:
            entry["latency_s"] = round(latency_s, 3)
        # ADR 0024 time ledger: first streamed delta, int ms; CLI single-blob
        # and non-streaming paths report first_token == total (disclosed)
        if first_token_ms is not None:
            entry["first_token_ms"] = int(first_token_ms)
        entry.update(extra)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        # ADR 0025: the 1-based row index this dispatch landed on (the
        # label surfaces key off it); lazily counted, then tracked in-memory
        if self._row_count is None:
            with self._path.open() as f:
                self._row_count = sum(1 for _ in f)
        else:
            self._row_count += 1
        return self._row_count

    # ---- ADR 0025 route-outcome labels ---------------------------------

    def read_rows(self) -> "list[dict]":
        if not self._path.exists():
            return []
        with self._path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def recent_rows(self, n: int = 10) -> "list[tuple[int, dict]]":
        """(row_index, row) newest-last for the label surfaces; row_index is
        the 1-based line number — stable because the file is append-only
        except for label attachment."""
        rows = self.read_rows()
        return [(i + 1, r) for i, r in enumerate(rows)][-n:]

    def set_outcome_label(self, row_index: int, label: str) -> dict:
        """Attach an outcome_label to a recorded dispatch row (atomic
        rewrite of that line; the ledger stays append-only otherwise)."""
        from kultivait.privacy import OUTCOME_LABELS

        if label not in OUTCOME_LABELS:
            raise ValueError(f"label must be one of {OUTCOME_LABELS}, got {label!r}")
        rows = self.read_rows()
        if not 1 <= row_index <= len(rows):
            raise IndexError(f"row index {row_index} out of range (1..{len(rows)})")
        rows[row_index - 1]["outcome_label"] = label
        tmp = self._path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        tmp.replace(self._path)
        return rows[row_index - 1]

    def label_last(self, n: int, label: str) -> int:
        """Label the newest n rows that carry no outcome_label yet."""
        rows = self.read_rows()
        targets = [i + 1 for i, r in enumerate(rows) if not r.get("outcome_label")][-n:]
        for idx in targets:
            self.set_outcome_label(idx, label)
        return len(targets)

    def clear_outcome_label(self, row_index: int) -> dict:
        rows = self.read_rows()
        if not 1 <= row_index <= len(rows):
            raise IndexError(f"row index {row_index} out of range (1..{len(rows)})")
        rows[row_index - 1].pop("outcome_label", None)
        tmp = self._path.with_suffix(".jsonl.tmp")
        with tmp.open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        tmp.replace(self._path)
        return rows[row_index - 1]

    def _energy_section(self, entries: list) -> dict:
        """ADR 0020: local-compute Wh only, estimated against a versioned
        coefficient table — never a counterfactual, never unlabeled."""
        local = [
            e for e in entries
            if e.get("local") and e.get("est_wh") is not None
        ]
        versions = [e.get("energy_model") for e in local if e.get("energy_model")]
        by_generation: dict = {}
        for e in local:
            gen = e.get("preprocess_model", "legacy/incumbent")
            g = by_generation.setdefault(gen, {"dispatches": 0, "est_wh": 0.0})
            g["dispatches"] += 1
            g["est_wh"] += e["est_wh"]
        return {
            "dispatches": len(local),
            "est_wh": round(sum(e["est_wh"] for e in local), 6),
            # latest tag present: old rows keep their table's numbers (ADR 0020)
            "version": max(versions) if versions else "",
            "by_generation": by_generation,
        }

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

    def _time_section(self, entries: list) -> dict:
        """ADR 0024 time ledger: local wall-clock per token band, measured
        against the frontier-latency reference table (harvest-time yardstick
        only — time-never-ranks). No table -> honest degrade, never fabricate."""
        from kultivait import time_reference as tr

        try:
            from kultivait.cli import CONFIG_PATH
            overrides = tr._load_overrides(CONFIG_PATH)
        except Exception:
            overrides = {}
        table = tr.medians(overrides)
        have_ref = tr.available(overrides)
        version = tr.active_version(overrides)

        def _med(vals: list) -> "int | None":
            vals = sorted(v for v in vals if v is not None)
            if not vals:
                return None
            n = len(vals)
            mid = n // 2
            return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) // 2

        def _p95(vals: list) -> "int | None":
            vals = sorted(v for v in vals if v is not None)
            if not vals:
                return None
            idx = min(len(vals) - 1, max(0, round(0.95 * (len(vals) - 1))))
            return vals[idx]

        local = [e for e in entries if e.get("local")]
        bands: dict = {}
        time_paid_ms = 0
        for band, _, _ in tr.BANDS:
            rows = [e for e in local if tr.band_for(int(e.get("tokens_in", 0))) == band]
            firsts = [e.get("first_token_ms") for e in rows]
            totals = [int(round(e["latency_s"] * 1000)) for e in rows if e.get("latency_s") is not None]
            ref = table.get(band)
            paid = None
            if have_ref and ref:
                # signed: local-faster-than-ref dispatches credit back
                paid = sum(t - ref["total_ms"] for t in totals)
                time_paid_ms += paid
            bands[band] = {
                "dispatches": len(rows),
                "local_first_token_ms_median": _med(firsts),
                "local_first_token_ms_p95": _p95(firsts),
                "local_total_ms_median": _med(totals),
                "local_total_ms_p95": _p95(totals),
                "ref_first_token_ms": ref["first_token_ms"] if ref else None,
                "ref_total_ms": ref["total_ms"] if ref else None,
                "time_paid_ms": paid,
            }
        return {
            "local_dispatches": len(local),
            "reference_version": version if have_ref else "",
            "has_reference": have_ref,
            "time_paid_min": round(time_paid_ms / 60000, 2) if have_ref else None,
            "bands": bands,
        }

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
        energy = self._energy_section(prompt_entries)
        time_ledger = self._time_section(prompt_entries)

        return {
            "cache": cache,
            "energy": energy,
            "time": time_ledger,
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
