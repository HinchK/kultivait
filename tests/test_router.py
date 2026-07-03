import numpy as np

from kultivait.router import Router

# Three orthogonal centroids make similarity unambiguous in tests.
TIERS = {
    "llama3.1:8b": np.array([1.0, 0.0, 0.0]),
    "qwen3:14b": np.array([0.0, 1.0, 0.0]),
    "claude": np.array([0.0, 0.0, 1.0]),
}
ORDER = ["llama3.1:8b", "qwen3:14b", "claude"]


def make_router(**kwargs):
    return Router(centroids=TIERS, capability_order=ORDER, **kwargs)


def test_routes_to_most_similar_tier():
    router = make_router()
    decision = router.classify(np.array([0.1, 0.9, 0.05]))
    assert decision.tier == "qwen3:14b"
    assert decision.escalated is False


def test_thin_margin_escalates_one_tier_up():
    router = make_router(escalation_margin=0.05)
    # Nearly equidistant between llama and qwen: winner's margin is thin,
    # so the decision should escalate one step up the capability order.
    decision = router.classify(np.array([1.0, 0.99, 0.0]))
    assert decision.tier == "qwen3:14b"
    assert decision.escalated is True


def test_thin_margin_at_top_tier_stays_at_top():
    router = make_router(escalation_margin=0.05)
    decision = router.classify(np.array([0.0, 0.99, 1.0]))
    assert decision.tier == "claude"
    assert decision.escalated is False
