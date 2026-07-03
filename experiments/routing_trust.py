# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "numpy"]
# ///
"""Routing-trust experiment: can a free local embedding model classify
prompt difficulty well enough to route between local and cloud models?

Method: 4 routing tiers, each with seed exemplars (used as centroids) and
held-out test prompts. Embed everything with nomic-embed-text via ollama,
classify test prompts by cosine similarity to tier centroids, and report
accuracy plus the dangerous-direction error rate (cloud-worthy prompts
misrouted to local models).
"""

import httpx
import numpy as np

OLLAMA = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

TIERS = {
    "llama3.1:8b": {  # trivial mechanical work
        "seeds": [
            "Rename this variable everywhere in the file",
            "Convert this dict to a JSON string",
            "Write a one-line docstring for this function",
            "Summarize this diff into a commit message",
            "Fix the indentation in this code block",
            "Add type hints to this function signature",
        ],
        "test": [
            "Reformat this list into a markdown table",
            "Write a commit message for these staged changes",
            "Convert this YAML config to TOML",
            "Rename the class and update all its references in this file",
            "Strip trailing whitespace and sort these imports",
            "Turn this comment into a proper docstring",
        ],
    },
    "qwen3:14b": {  # local reasoning
        "seeds": [
            "Why does this async test deadlock intermittently?",
            "Explain why this loop produces off-by-one results",
            "What race condition could cause this flaky behavior?",
            "Walk through this recursion and find the base-case bug",
            "Why is this regex catastrophically backtracking?",
            "Diagnose why this cache returns stale values",
        ],
        "test": [
            "Why does this mutex sometimes fail to release?",
            "Explain the logic error in this binary search",
            "What causes this generator to skip the last element?",
            "Why does this date parsing break at month boundaries?",
            "Find the reason this retry loop never terminates",
            "Why is this SQL query returning duplicate rows?",
        ],
    },
    "claude": {  # cross-file architecture / high-stakes
        "seeds": [
            "Refactor the auth module across all fourteen files",
            "Design a migration plan from the monolith to services",
            "Review this payment flow for security vulnerabilities",
            "Restructure the plugin system to support hot reloading",
            "Plan how to split this package without breaking the public API",
            "Redesign the error handling strategy across the codebase",
        ],
        "test": [
            "Refactor the session layer and update every consumer",
            "Architect a multi-tenant permission model for this app",
            "Audit this OAuth implementation for token-leak risks",
            "Design the rollback strategy for this schema migration",
            "Reorganize these twelve modules into a coherent package layout",
            "Propose an event-driven redesign of the sync pipeline",
        ],
    },
    "gemini:agy": {  # doc-grounded / freshness-dependent
        "seeds": [
            "Cross-check this config against the current Gemini docs",
            "What is the latest stable version of this API?",
            "Verify these flags against the current CLI documentation",
            "Does the newest SDK release still support this method?",
            "Check the current rate limits documented for this endpoint",
            "What changed in the most recent release notes?",
        ],
        "test": [
            "Confirm this matches the current official documentation",
            "Is this parameter still supported in the latest version?",
            "Look up the current pricing for this model tier",
            "Check whether the docs still recommend this pattern",
            "What does the changelog say about this deprecation?",
            "Verify this against the API reference published this month",
        ],
    },
}

# Escalation order: misrouting DOWN this list is dangerous (too-dumb model),
# misrouting UP is merely wasteful (too-expensive model).
CAPABILITY_ORDER = ["llama3.1:8b", "qwen3:14b", "gemini:agy", "claude"]


def embed(texts: list[str]) -> np.ndarray:
    r = httpx.post(
        f"{OLLAMA}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=120,
    )
    r.raise_for_status()
    v = np.array(r.json()["embeddings"])
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main() -> None:
    centroids = {}
    for tier, data in TIERS.items():
        seed_vecs = embed(data["seeds"])
        c = seed_vecs.mean(axis=0)
        centroids[tier] = c / np.linalg.norm(c)

    tier_names = list(TIERS)
    cmatrix = np.stack([centroids[t] for t in tier_names])

    total = correct = dangerous = 0
    rows = []
    for true_tier, data in TIERS.items():
        test_vecs = embed(data["test"])
        sims = test_vecs @ cmatrix.T
        for prompt, sim in zip(data["test"], sims):
            pred = tier_names[int(sim.argmax())]
            margin = float(np.sort(sim)[-1] - np.sort(sim)[-2])
            ok = pred == true_tier
            danger = (
                CAPABILITY_ORDER.index(pred) < CAPABILITY_ORDER.index(true_tier)
            )
            total += 1
            correct += ok
            dangerous += (not ok) and danger
            rows.append((prompt, true_tier, pred, margin, ok, danger))

    print(f"{'prompt':<58} {'true':<12} {'predicted':<12} margin")
    print("-" * 96)
    for prompt, true_tier, pred, margin, ok, danger in rows:
        flag = "  " if ok else ("!!" if danger else " ~")
        print(f"{flag} {prompt[:55]:<56} {true_tier:<12} {pred:<12} {margin:.3f}")

    print("-" * 96)
    print(f"accuracy: {correct}/{total} ({100 * correct / total:.0f}%)")
    print(f"dangerous misroutes (cloud-worthy -> weaker model): {dangerous}/{total}")
    print(f"wasteful misroutes (over-provisioned): {total - correct - dangerous}/{total}")


if __name__ == "__main__":
    main()
