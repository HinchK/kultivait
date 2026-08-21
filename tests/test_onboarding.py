"""onboarding marker: magnitude writes {completed:true} once and never
un-sets it; kultivait adds skipped/completed_at for the skip path."""

import json

from kultivait import onboarding


def test_missing_marker_is_incomplete(tmp_path):
    assert onboarding.is_complete(tmp_path / "onboarding.json") is False


def test_complete_roundtrip_and_skip_flag(tmp_path):
    p = tmp_path / "onboarding.json"
    onboarding.complete(skipped=True, path=p)
    assert onboarding.is_complete(p) is True
    data = json.loads(p.read_text())
    assert data["completed"] is True
    assert data["skipped"] is True
    assert data["completed_at"]


def test_corrupt_marker_is_incomplete_not_a_crash(tmp_path):
    p = tmp_path / "onboarding.json"
    p.write_text("{not json")
    assert onboarding.is_complete(p) is False


def test_complete_is_idempotent(tmp_path):
    p = tmp_path / "onboarding.json"
    onboarding.complete(path=p)
    onboarding.complete(path=p)  # re-runs must not raise
    assert onboarding.is_complete(p) is True
