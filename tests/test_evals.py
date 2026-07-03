from kultivait.evals import score_brief

# A planted fact is retained if ANY anchor group has ALL its terms present
# (case-insensitive). Groups express paraphrase alternatives.
FACTS = [
    {"name": "redis-not-local", "groups": [["redis", "process-local"], ["redis", "shared"]]},
    {"name": "tier-rates", "groups": [["10", "300"]]},
    {"name": "fakeredis-injection", "groups": [["inject"], ["fakeredis"]]},
]


def test_recall_counts_facts_whose_anchors_appear():
    brief = "Use the shared Redis, never process-local state. Rates: free=10/min, pro=300/min."
    result = score_brief(brief, FACTS)
    assert result.recall == 2 / 3
    assert result.missing == ["fakeredis-injection"]


def test_alternative_anchor_groups_count_as_retained():
    brief = "The limiter must accept an injected client for tests."
    result = score_brief(brief, FACTS)
    assert "fakeredis-injection" not in result.missing


def test_matching_is_case_insensitive():
    brief = "FakeRedis fixtures require an Injected client."
    result = score_brief(brief, [{"name": "fakeredis-injection", "groups": [["fakeredis"]]}])
    assert result.recall == 1.0
