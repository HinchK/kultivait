"""Shared pytest setup.

Unit tests must make zero outbound network calls; the suite stays hermetic.
"""


import pytest


@pytest.fixture(autouse=True)
def _isolated_egress_policy(tmp_path, monkeypatch):
    """Every test gets an isolated egress policy defaulting to allow, so
    pre-#225 frontier-serving behavior is preserved hermetically; egress
    tests override these paths explicitly for their own postures."""
    from kultivait import egress

    policy = tmp_path / "egress_policy.json"
    policy.write_text('{"global": "allow", "repos": {}}')
    monkeypatch.setattr(egress, "POLICY_PATH", policy)
    monkeypatch.setattr(egress, "PENDING_PATH", tmp_path / "egress_pending.json")
