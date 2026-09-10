"""ADR 0022 parity pin: the README distiller table must equal the table
mechanically derived from experiments/distill_eval/results.json. Hand-drift
(the #136 finding) is structurally impossible: change one, the other fails."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "experiments" / "distill_eval"))

from run import build_readme_table  # noqa: E402


def test_readme_distiller_table_matches_results_json():
    results = json.loads(
        (HERE / "experiments" / "distill_eval" / "results.json").read_text()
    )
    expected = build_readme_table(results)
    readme = (HERE / "README.md").read_text()
    assert expected in readme, (
        "README distiller table has drifted from experiments/distill_eval/"
        "results.json — regenerate with: uv run python "
        "experiments/distill_eval/run.py --emit-table"
    )


def test_results_carry_generation_loss_everywhere():
    results = json.loads(
        (HERE / "experiments" / "distill_eval" / "results.json").read_text()
    )
    assert results, "results.json emptied without a protocol-v3 registration"
    missing = [r for r in results if "gen2_recall" not in r]
    assert not missing, f"{len(missing)} rows lack gen2_recall — partial sweep"
