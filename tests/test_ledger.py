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


def test_record_stores_extra_decision_fields(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=100, tokens_out=10, cost_usd=0.0,
        requested_tier="claude", margin=0.045, fallback_reason="tools_unsupported",
        truncated=False, snippet="draft a technical spec",
    )
    import json
    entry = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert entry["requested_tier"] == "claude"
    assert entry["fallback_reason"] == "tools_unsupported"
    assert entry["snippet"] == "draft a technical spec"


def test_harvest_reports_escalations_and_truncations(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.record(tier="llama3.1:8b", local=True, tokens_in=10, tokens_out=5, cost_usd=0.0)
    ledger.record(
        tier="qwen3:14b", local=True, tokens_in=8191, tokens_out=10, cost_usd=0.0,
        requested_tier="claude", fallback_reason="no_backend", truncated=True,
        snippet="draft a technical spec",
    )
    stats = ledger.harvest()
    assert stats["escalations"]["count"] == 1
    assert stats["escalations"]["recent"] == [
        {"requested": "claude", "served": "qwen3:14b", "snippet": "draft a technical spec"}
    ]
    assert stats["truncated_inputs"] == 1


def test_harvest_survives_restart(tmp_path):
    path = tmp_path / "ledger.jsonl"
    Ledger(path).record(tier="llama3.1:8b", local=True, tokens_in=10, tokens_out=10, cost_usd=0.0)
    stats = Ledger(path).harvest()
    assert stats["prompts"] == 1


def test_record_new_route_metadata_fields(tmp_path):
    import json
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.record(
        tier="claude",
        local=False,
        tokens_in=1250,
        tokens_out=450,
        cost_usd=0.0105,
        fingerprint="a1b2c3d4e5f6",
        preprocess_mark="ok",
        verdict="contested",
        max_fit=0.82,
        target_fits={"claude": 0.82, "codex": 0.75, "agy": 0.60},
        canonical_effort="balanced",
        cli_effort_flags=["--effort", "medium"],
        toll="answered",
        route_choice="human:frontier:claude",
        subtask_candidates=3,
        orchestrator="claude-code",
        worker="agy-gemini-3.7-flash",
    )
    entry = json.loads(path.read_text())
    assert entry["fingerprint"] == "a1b2c3d4e5f6"
    assert entry["preprocess_mark"] == "ok"
    assert entry["verdict"] == "contested"
    assert entry["max_fit"] == 0.82
    assert entry["target_fits"] == {"claude": 0.82, "codex": 0.75, "agy": 0.60}
    assert entry["canonical_effort"] == "balanced"
    assert entry["cli_effort_flags"] == ["--effort", "medium"]
    assert entry["toll"] == "answered"
    assert entry["route_choice"] == "human:frontier:claude"
    assert entry["subtask_candidates"] == 3
    assert entry["orchestrator"] == "claude-code"
    assert entry["worker"] == "agy-gemini-3.7-flash"
    assert "ts" in entry


def test_record_fingerprint_optional_omitted(tmp_path):
    import json
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.record(tier="qwen3:14b", local=True, tokens_in=100, tokens_out=20, cost_usd=0.0)
    entry = json.loads(path.read_text())
    assert "fingerprint" not in entry


def test_harvest_mixed_records_toll_activity(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)

    # 1. Legacy record without toll fields
    ledger.record(tier="llama3.1:8b", local=True, tokens_in=100, tokens_out=50, cost_usd=0.0)

    # 2. Toll answered
    ledger.record(
        tier="claude",
        local=False,
        tokens_in=500,
        tokens_out=200,
        cost_usd=0.005,
        fingerprint="fp1",
        preprocess_mark="ok",
        verdict="contested",
        toll="answered",
        route_choice="human:frontier:claude",
    )

    # 3. Toll expired (auto-policy local)
    ledger.record(
        tier="qwen3:14b",
        local=True,
        tokens_in=300,
        tokens_out=100,
        cost_usd=0.0,
        fingerprint="fp2",
        preprocess_mark="ok",
        verdict="contested",
        toll="expired",
        route_choice="auto:local",
    )

    # 4. Toll skipped (uncontested frontier)
    ledger.record(
        tier="codex",
        local=False,
        tokens_in=400,
        tokens_out=150,
        cost_usd=0.004,
        fingerprint="fp3",
        preprocess_mark="ok",
        verdict="frontier",
        toll="skipped",
        route_choice="auto:frontier:codex",
    )

    # 5. Preprocess timeout
    ledger.record(
        tier="qwen3:14b",
        local=True,
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.0,
        preprocess_mark="preprocess_timeout",
        verdict="local",
    )

    stats = ledger.harvest()
    assert stats["prompts"] == 5
    toll_act = stats["toll_activity"]
    assert toll_act["fired"] == 2
    assert toll_act["answered"] == 1
    assert toll_act["expired"] == 1
    assert toll_act["skipped"] == 1
    assert abs(toll_act["toll_rate"] - 0.4) < 1e-9

    assert toll_act["route_choices"] == {
        "human:frontier:claude": 1,
        "auto:local": 1,
        "auto:frontier:codex": 1,
    }
    assert toll_act["route_choice_groups"]["human:frontier"] == 1
    assert toll_act["route_choice_groups"]["auto:local"] == 1
    assert toll_act["route_choice_groups"]["auto:frontier"] == 1
    assert toll_act["route_choice_groups"]["human:local"] == 0

    assert toll_act["preprocess_marks"] == {
        "ok": 3,
        "skipped": 0,
        "timeout": 1,
        "fail": 0,
    }


def test_harvest_legacy_only_all_zeros(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.record(tier="llama3.1:8b", local=True, tokens_in=10, tokens_out=10, cost_usd=0.0)

    stats = ledger.harvest()
    assert stats["prompts"] == 1
    toll_act = stats["toll_activity"]
    assert toll_act["fired"] == 0
    assert toll_act["answered"] == 0
    assert toll_act["expired"] == 0
    assert toll_act["skipped"] == 0
    assert toll_act["toll_rate"] == 0.0
    assert toll_act["route_choices"] == {}
    assert toll_act["preprocess_marks"] == {"ok": 0, "skipped": 0, "timeout": 0, "fail": 0}

