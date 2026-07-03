"""Planted-fact recall scoring for distillation quality.

A fact is a dict: {"name": str, "groups": [[term, ...], ...]}. The fact is
retained if any group has all of its terms present in the brief,
case-insensitively. Groups express paraphrase alternatives.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecallResult:
    recall: float
    missing: list[str]


def score_brief(brief: str, facts: list[dict]) -> RecallResult:
    text = brief.lower()
    missing = [
        fact["name"]
        for fact in facts
        if not any(all(term.lower() in text for term in group) for group in fact["groups"])
    ]
    return RecallResult(recall=(len(facts) - len(missing)) / len(facts), missing=missing)
