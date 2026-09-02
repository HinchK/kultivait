"""H3 (#90) tests: context-scale workloads — token floors, determinism, wiring."""

import json
from pathlib import Path

import pytest

from kultivait.capability_eval import TaskCase, load_corpus, run_task
from kultivait.context_gen import materialize, render_module


def _working_tokens(t) -> int:
    blob = t.context_text + json.dumps(t.tools) + json.dumps(t.messages)
    return len(blob) // 4


# ---------------------------------------------------------------- band floors


def test_escalatory_context_exceeds_16k():
    sizes = [_working_tokens(t) for t in load_corpus()
             if t.rubric["band"] == "escalatory"]
    assert len(sizes) == 7
    assert min(sizes) >= 16000


def test_contested_context_about_8k():
    sizes = [_working_tokens(t) for t in load_corpus()
             if t.rubric["band"] == "contested"]
    assert len(sizes) == 7
    assert 7500 <= min(sizes) and max(sizes) <= 9500


def test_simple_context_compact():
    sizes = [_working_tokens(t) for t in load_corpus()
             if t.rubric["band"] == "simple"]
    assert max(sizes) <= 2500  # sanity baseline stays cheap


def test_multi_file_spread_in_escalatory():
    tasks = {t.id: t for t in load_corpus()}
    esc = [t for t in tasks.values() if t.rubric["band"] == "escalatory"]
    # every escalatory task spans 5+ context files
    raw = json.loads(Path("evals/capability_corpus/tasks.json").read_text())
    esc_ids = {t.id for t in esc}
    for t in raw:
        if t["id"] in esc_ids:
            assert len(t["context_files"]) >= 5


# ---------------------------------------------------------------- far-facts


def test_far_facts_embedded_deep_and_cited():
    raw = json.loads(Path("evals/capability_corpus/tasks.json").read_text())
    far = [t for t in raw if t.get("far_fact")]
    assert len(far) >= 3  # at least the ticket's "one task"; we ship three
    tasks = {t.id: t for t in load_corpus()}
    for spec in far:
        t = tasks[spec["id"]]
        assert spec["far_fact"].split(":")[0] in t.context_text  # embedded...
        # ...at the tail of the LAST module (far from the prompt focus)
        assert t.context_text.rstrip().endswith(spec["far_fact"])
        # ...and the rubric demands it
        assert any(any(k in c for k in ("deep-conte", "authoritative", "recorded deep",
                                         "ownership record", "deep in the repository"))
                   for c in t.rubric["criteria"])


# ---------------------------------------------------------------- determinism


def test_materialize_is_deterministic():
    spec = [["a.py", 120], ["b.py", 80]]
    assert materialize(spec, "s1") == materialize(spec, "s1")
    assert materialize(spec, "s1") != materialize(spec, "s2")
    assert render_module("a.py", 100, "s").splitlines()[0].startswith('"""a.py')


# ---------------------------------------------------------------- harness wiring


class StubBackend:
    supports_tools = True
    local = False

    def complete(self, messages, tools=None, canonical_effort="balanced", **kw):
        captured.append(list(messages))
        from kultivait.backends import Completion
        return Completion(text="done", tokens_in=1, tokens_out=1, cost_usd=0.0,
                          local=False)

    def stream(self, *a, **kw):
        yield "done"


captured: list = []


def test_run_task_prepends_context_as_system():
    captured.clear()
    task = TaskCase(id="ctx_probe", name="", description="",
                    messages=[{"role": "user", "content": "audit the boundary"}],
                    tools=[], mock_responses={},
                    context_text="MODULE_ZERO = 42  # deep context probe",
                    rubric={"band": "escalatory"}, max_turns=1)
    run_task(StubBackend(), task)
    msgs = captured[0]
    assert msgs[0]["role"] == "system"
    assert "MODULE_ZERO" in msgs[0]["content"]
    assert msgs[-1]["content"] == "audit the boundary"


def test_no_context_leaves_messages_untouched():
    captured.clear()
    task = TaskCase(id="plain", name="", description="",
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[], mock_responses={}, context_text="",
                    rubric={}, max_turns=1)
    run_task(StubBackend(), task)
    assert captured[0][0]["content"] == "hi"


def test_bands_unchanged():
    from collections import Counter
    bands = Counter(t.rubric["band"] for t in load_corpus())
    assert bands == {"simple": 7, "contested": 7, "escalatory": 7}
