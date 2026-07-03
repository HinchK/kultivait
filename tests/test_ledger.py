from kultivait.ledger import Ledger


def test_harvest_sums_savings_against_frontier_baseline(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl", baseline_in=3.0, baseline_out=15.0)
    ledger.record(tier="llama3.1:8b", local=True, tokens_in=1000, tokens_out=500, cost_usd=0.0)
    ledger.record(tier="qwen3:14b", local=True, tokens_in=2000, tokens_out=1000, cost_usd=0.0)
    ledger.record(tier="claude", local=False, tokens_in=1000, tokens_out=1000, cost_usd=0.018)

    stats = ledger.harvest()

    assert stats["prompts"] == 3
    assert stats["local_prompts"] == 2
    assert stats["tokens_local"] == 4500
    assert stats["spent_usd"] == 0.018
    # baseline: every prompt at frontier prices ($3/M in, $15/M out)
    # in: 4000 tokens * 3/1e6 = 0.012; out: 2500 * 15/1e6 = 0.0375
    assert abs(stats["baseline_usd"] - 0.0495) < 1e-9
    assert abs(stats["saved_usd"] - 0.0315) < 1e-9


def test_harvest_survives_restart(tmp_path):
    path = tmp_path / "ledger.jsonl"
    Ledger(path).record(tier="llama3.1:8b", local=True, tokens_in=10, tokens_out=10, cost_usd=0.0)
    stats = Ledger(path).harvest()
    assert stats["prompts"] == 1
