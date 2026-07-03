"""Routing seed prompts per role, validated in experiments/routing_trust.py (24/24).

Roles are the stable classification space; which model serves each role is
the machine-specific config's business (see config.detect)."""

ROLE_SEEDS: dict[str, list[str]] = {
    "simple": [
        "Rename this variable everywhere in the file",
        "Convert this dict to a JSON string",
        "Write a one-line docstring for this function",
        "Summarize this diff into a commit message",
        "Fix the indentation in this code block",
        "Add type hints to this function signature",
    ],
    "reasoning": [
        "Why does this async test deadlock intermittently?",
        "Explain why this loop produces off-by-one results",
        "What race condition could cause this flaky behavior?",
        "Walk through this recursion and find the base-case bug",
        "Why is this regex catastrophically backtracking?",
        "Diagnose why this cache returns stale values",
    ],
    "docs": [
        "Cross-check this config against the current Gemini docs",
        "What is the latest stable version of this API?",
        "Verify these flags against the current CLI documentation",
        "Does the newest SDK release still support this method?",
        "Check the current rate limits documented for this endpoint",
        "What changed in the most recent release notes?",
    ],
    "architect": [
        "Refactor the auth module across all fourteen files",
        "Design a migration plan from the monolith to services",
        "Review this payment flow for security vulnerabilities",
        "Restructure the plugin system to support hot reloading",
        "Plan how to split this package without breaking the public API",
        "Redesign the error handling strategy across the codebase",
    ],
}
