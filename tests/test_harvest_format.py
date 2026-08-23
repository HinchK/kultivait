from kultivait.cli import format_harvest

STATS = {
    "prompts": 18,
    "local_prompts": 18,
    "tokens_local": 105607,
    "spent_usd": 0.0,
    "baseline_usd": 0.4018,
    "saved_usd": 0.4018,
    "escalations": {
        "count": 2,
        "recent": [
            {"requested": "claude", "served": "qwen3:14b", "snippet": "draft a technical spec"},
        ],
    },
    "truncated_inputs": 9,
}


def test_format_harvest_shows_the_headline_numbers():
    out = format_harvest(STATS)
    assert "18" in out and "100% local" in out
    assert "$0.40" in out          # saved
    assert "105,607" in out        # local tokens, readable
    assert "2 cloud-worthy" in out
    assert "draft a technical spec" in out
    assert "9" in out              # truncated inputs surfaced


def test_format_harvest_handles_empty_season():
    out = format_harvest(
        {
            "prompts": 0, "local_prompts": 0, "tokens_local": 0,
            "spent_usd": 0.0, "baseline_usd": 0.0, "saved_usd": 0.0,
            "escalations": {"count": 0, "recent": []}, "truncated_inputs": 0,
        }
    )
    assert "nothing planted yet" in out


def test_format_harvest_with_toll_activity():
    stats = {
        "prompts": 20,
        "local_prompts": 15,
        "tokens_local": 50000,
        "spent_usd": 0.02,
        "baseline_usd": 0.50,
        "saved_usd": 0.48,
        "escalations": {"count": 0, "recent": []},
        "truncated_inputs": 0,
        "toll_activity": {
            "fired": 4,
            "answered": 3,
            "expired": 1,
            "skipped": 2,
            "toll_rate": 0.20,
            "route_choices": {
                "human:frontier:claude": 2,
                "human:local": 1,
                "auto:local": 1,
            },
            "route_choice_groups": {
                "human:frontier": 2,
                "human:local": 1,
                "auto:local": 1,
                "auto:frontier": 0,
            },
            "preprocess_marks": {
                "ok": 5,
                "skipped": 2,
                "timeout": 1,
                "fail": 0,
            },
        },
    }
    out = format_harvest(stats)
    assert "toll activity" in out
    assert "tolls fired" in out and "4" in out and "20% toll rate" in out
    assert "answered 3, expired 1, skipped 2" in out
    assert "human:frontier:claude" in out
    assert "preprocessor marks" in out
    assert "ok: 5, skipped: 2, timeout: 1, fail: 0" in out


def test_format_harvest_legacy_all_zeros():
    stats_with_zeros = dict(STATS)
    stats_with_zeros["toll_activity"] = {
        "fired": 0,
        "answered": 0,
        "expired": 0,
        "skipped": 0,
        "toll_rate": 0.0,
        "route_choices": {},
        "route_choice_groups": {
            "human:frontier": 0,
            "human:local": 0,
            "auto:local": 0,
            "auto:frontier": 0,
        },
        "preprocess_marks": {"ok": 0, "skipped": 0, "timeout": 0, "fail": 0},
    }
    out = format_harvest(stats_with_zeros)
    # When all toll counts are 0, Toll Activity section is omitted (backward compat)
    assert "toll activity" not in out
    assert format_harvest(STATS) == out

