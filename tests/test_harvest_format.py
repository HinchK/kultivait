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
