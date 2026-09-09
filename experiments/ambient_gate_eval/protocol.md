# Ambient-gates brief-quality eval — pre-registered protocol

Ticket: [#160](https://github.com/Standard-Pentest/kultivait/issues/160) · map: [#156](https://github.com/Standard-Pentest/kultivait/issues/156) · ADR 0019
Registered: 2026-09-08, **before any run** (ADR 0015 discipline). Bars are final; results land in `results.md` beside this file; FAIL branches are reported honestly and dispositioned (ADR 0017 discipline).

## Subject

The shipped ambient-gate path — `ambient.fire()` with the real standalone gate
(`build_gate(get_config())`, distill model from live config: `qwen3:14b` via ollama) — over
synthetic Claude-Code-style transcripts, SubagentStop-shaped payloads, isolated `$HOME`.

## Harness

`experiments/ambient_gate_eval/run_eval.py` generates 10 synthetic transcript JSONL files
(~2–4k source tokens each), each seeded with **6 planted facts** (2 file paths, 2 constraints,
2 decisions — listed per transcript in `planted.json`), fires the gate per transcript, and scores
the emitted briefs. Normalized matching: case-insensitive, whitespace-collapsed substring.

## Pre-registered gates (pass/fail bars)

| Gate | Metric | Bar |
|---|---|---|
| **G1 brief recall** | planted facts retained in brief, mean across 10 transcripts | **mean ≥ 80%** |
| **G1b worst case** | lowest single-transcript recall | **≥ 60%** |
| **G2 tokens-kept** | `tokens_after / tokens_before`, mean | **≤ 60%** |
| **G3 durability** | kill -9 mid-distill trials leaving a compost file with the full transcript | **≥ 3/3** |
| **G4 injection latency** | `latest_brief_block()` wall time, p95 | **≤ 50 ms** |
| **G5 sync-prefix budget** | fire() entry → compost write complete, p95 | **≤ 1000 ms** |

## Pre-declared dispositions

- Any gate FAIL: recorded in `results.md` with the raw numbers, no re-run until the cause is
  understood; a small fix requires a **full re-run** (all five gates) — no partial re-scoring.
- G1/G1b FAIL blocks #161 (dogfood) until fixed; G3 FAIL blocks #161 unconditionally
  (durability is the safety spine); G4/G5 FAIL blocks #161 until dispositioned.
- The eval's synthetic transcripts and plantings are committed with the results for
  reproduction; `uv run pytest -q` must remain green throughout.
