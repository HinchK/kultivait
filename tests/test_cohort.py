"""#226: design-partner cohort reporting and lifecycle.

Covers multi-export ingestion, the five ratified lenses (regret formula
EXACTLY wrong_route ÷ labeled — unlabeled never enters the denominator),
breakdowns, formatting, and the deletion helpers (partner exit + post-memo
cleanup, both logged).
"""

import json
import time
from pathlib import Path
from types import SimpleNamespace

from kultivait import cohort
from kultivait.cli import cmd_report


def _row(**kw):
    base = dict(ts=1700000000.0, tier="qwen3:14b", local=True, cloud_egress=False,
                outcome_label=None, policy_version="v0.5.0-dp", repo_hash="hashA",
                tokens_in=500, tokens_out=20, latency_s=3.0, first_token_ms=900,
                cost_usd=0.0, notional_usd=0.0)
    base.update(kw)
    return base


def _write_cohort(tmp_path):
    d = tmp_path / "cohort"
    d.mkdir()
    # partner 1: 3 labeled (1 wrong), one cloud dispatch with metered cash
    rows1 = [
        _row(outcome_label="accepted"),
        _row(outcome_label="wrong_route"),
        _row(outcome_label="accepted"),
        _row(),  # unlabeled — must NOT enter the regret denominator
        _row(tier="claude", local=False, cloud_egress=True,
             cost_usd=0.012, notional_usd=0.012, tokens_in=1000, tokens_out=200),
    ]
    (d / "partner1.jsonl").write_text(
        "\n".join(json.dumps({k: v for k, v in r.items()}) for r in rows1) + "\n")
    # partner 2: 2 labeled (0 wrong)
    rows2 = [_row(repo_hash="hashB", outcome_label="accepted"),
             _row(repo_hash="hashB", outcome_label="retried")]
    (d / "partner2.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows2) + "\n")
    return d


def test_cohort_ingestion_dir_and_list(tmp_path):
    d = _write_cohort(tmp_path)
    rows, files = cohort.load_cohort(d)
    assert len(rows) == 7 and len(files) == 2
    rows2, _ = cohort.load_cohort([d / "partner1.jsonl", d / "partner2.jsonl"])
    assert len(rows2) == 7
    assert {r["_source"] for r in rows} == {"partner1.jsonl", "partner2.jsonl"}


def test_regret_uses_the_ratified_denominator(tmp_path):
    d = _write_cohort(tmp_path)
    rows, _ = cohort.load_cohort(d)
    r = cohort.cohort_report(rows)
    rr = r["route_regret"]
    # 1 wrong_route / 5 labeled (the unlabeled row and... wait: 3+2 labeled)
    assert rr["wrong_route"] == 1
    assert rr["labeled"] == 5
    assert rr["regret"] == 0.2
    assert rr["ceiling"] == 0.10
    assert rr["within_ceiling"] is False


def test_regret_none_without_labels():
    r = cohort.cohort_report([_row(), _row()])
    assert r["route_regret"]["regret"] is None
    assert r["route_regret"]["within_ceiling"] is None


def test_five_lenses_math(tmp_path):
    d = _write_cohort(tmp_path)
    rows, _ = cohort.load_cohort(d)
    r = cohort.cohort_report(rows)
    assert r["billed_metered_cash_usd"] == 0.012          # cloud rows only
    tokens_in = 500 * 4 + 1000 + 500 * 2
    tokens_out = 20 * 4 + 200 + 20 * 2
    baseline = (tokens_in * 3.0 + tokens_out * 15.0) / 1e6
    assert abs(r["baseline_usd"] - round(baseline, 4)) < 1e-9
    assert r["counterfactual_savings_usd"] == round(baseline - 0.012, 4)
    assert r["observed_latency"]["first_token_ms_p50"] == 900
    assert r["estimated_time"]["cloud_dispatches"] == 1
    assert r["dispatches"] == 7 and r["labeled"] == 5


def test_breakdowns_by_tier_band_repo_and_partner(tmp_path):
    d = _write_cohort(tmp_path)
    rows, _ = cohort.load_cohort(d)
    b = cohort.cohort_report(rows)["breakdowns"]
    assert b["by_tier"]["qwen3:14b"]["dispatches"] == 6
    assert b["by_tier"]["claude"]["dispatches"] == 1
    assert b["by_band"]["0-2k"]["dispatches"] == 7
    assert b["by_repo"]["hashA"]["dispatches"] == 5
    assert b["by_repo"]["hashB"]["dispatches"] == 2
    assert b["by_partner_file"]["partner1.jsonl"]["dispatches"] == 5
    assert b["by_partner_file"]["partner2.jsonl"]["regret"] == 0.0


def test_format_cohort_report_renders_lenses_and_ceiling(tmp_path):
    d = _write_cohort(tmp_path)
    rows, _ = cohort.load_cohort(d)
    text = cohort.format_cohort_report(cohort.cohort_report(rows))
    assert "cohort quality report" in text
    assert "route regret" in text and "OVER the 10% ceiling" in text
    assert "wrong_route ÷ labeled" in text  # the ratified-formula note


def test_cmd_report_cohort_end_to_end(tmp_path, capsys):
    d = _write_cohort(tmp_path)
    args = SimpleNamespace(export=False, out=None, include_snippets=False,
                           cohort=str(d), purge_repo=None, purge_older_than=None,
                           json=False)
    cmd_report(args)
    out = capsys.readouterr().out
    assert "route regret" in out and "partner1.jsonl" in out

    args.json = True
    cmd_report(args)
    data = json.loads(capsys.readouterr().out)
    assert data["route_regret"]["labeled"] == 5


def test_purge_partner_exports_only_that_repo(tmp_path):
    d = _write_cohort(tmp_path)
    log = tmp_path / "del.jsonl"
    # hashB lives only in partner2's file
    removed = cohort.purge_partner_exports("hashB", d, log)
    assert removed == ["partner2.jsonl"]
    assert (d / "partner1.jsonl").exists() and not (d / "partner2.jsonl").exists()
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert entries[0]["reason"] == "partner_exit" and entries[0]["repo_hash"] == "hashB"


def test_purge_older_exports_by_mtime(tmp_path):
    d = _write_cohort(tmp_path)
    log = tmp_path / "del.jsonl"
    old = d / "partner1.jsonl"
    now = time.time()
    import os
    os.utime(old, (now - 100 * 86400, now - 100 * 86400))
    removed = cohort.purge_older_exports(d, older_than_days=90, log_path=log, now=now)
    assert removed == ["partner1.jsonl"]
    assert (d / "partner2.jsonl").exists()
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert entries[0]["reason"] == "post_memo_cleanup"


def test_cmd_report_purge_flags(tmp_path, capsys):
    d = _write_cohort(tmp_path)
    args = SimpleNamespace(export=False, out=None, include_snippets=False,
                           cohort=str(d), purge_repo="hashA",
                           purge_older_than=None, json=False)
    cmd_report(args)
    out = capsys.readouterr().out
    assert "partner exit: removed 1 export file(s): partner1.jsonl" in out
    args2 = SimpleNamespace(export=False, out=None, include_snippets=False,
                            cohort=str(d), purge_repo=None,
                            purge_older_than=90, json=False)
    cmd_report(args2)
    out = capsys.readouterr().out
    assert "post-memo cleanup" in out
