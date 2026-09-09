"""Ambient gates (ADR 0019): core invariants, briefs lane, install surface."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kultivait import ambient
from kultivait.gates import Gate, HandoffBrief


# ---------- fakes ----------


@dataclass
class FakeGate:
    brief: str = "FINDINGS: none\nDECISIONS: none\nCONSTRAINTS: none\nOPEN QUESTIONS: none"
    tokens_before: int = 400
    tokens_after: int = 100

    def __init__(self, *a, **k) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def distill(self, transcript: str, *, from_phase: str, to_phase: str) -> HandoffBrief:
        self.calls.append((transcript, from_phase, to_phase))
        return HandoffBrief(
            brief=self.brief,
            tokens_before=max(1, len(transcript) // 4),
            tokens_after=25,
            compost_id="test",
        )


def fake_make_gate() -> FakeGate:
    gate = FakeGate()
    fake_make_gate.last = gate
    return gate


fake_make_gate.last = None  # type: ignore[attr-defined]


def transcript_jsonl(*turns: tuple[str, str]) -> str:
    lines = []
    for role, text in turns:
        lines.append(
            json.dumps(
                {
                    "type": "message",
                    "message": {"role": role, "content": text},
                }
            )
        )
    lines.append(json.dumps({"type": "summary", "summary": "ignored"}))
    return "\n".join(lines)


def subagent_stop_payload(tmp_path: Path, **extra) -> dict:
    tpath = tmp_path / "agent-transcript.jsonl"
    tpath.write_text(
        transcript_jsonl(
            ("user", "explore the parser"),
            ("assistant", "found the bug at parser.py:12"),
        )
    )
    return {
        "hook_event_name": "SubagentStop",
        "cwd": str(tmp_path),
        "agent_transcript_path": str(tpath),
        "agent_type": "explorer",
        "last_assistant_message": "fallback text",
        **extra,
    }


# ---------- pure functions ----------


def test_project_key_stable_and_collision_safe(tmp_path):
    a = ambient.project_key(str(tmp_path))
    assert a == ambient.project_key(str(tmp_path))
    b = ambient.project_key(str(tmp_path / "elsewhere"))
    assert a != b or tmp_path.name == (tmp_path / "elsewhere").name


def test_extract_transcript_keeps_turns_drops_noise():
    text = transcript_jsonl(("user", "hi"), ("assistant", "hello"))
    out = ambient.extract_transcript(text)
    assert "user: hi" in out and "assistant: hello" in out
    assert "ignored" not in out


def test_extract_transcript_list_content_blocks():
    line = json.dumps(
        {
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "part one"},
                    {"type": "text", "text": "part two"},
                    {"type": "tool_use", "id": "t1"},
                ],
            }
        }
    )
    out = ambient.extract_transcript(line)
    assert "part one" in out and "part two" in out and "t1" not in out


def test_resolve_phases_default_without_toml(tmp_path):
    assert ambient.resolve_phases("SubagentStop", {"cwd": str(tmp_path)}) == ("previous", "next")


def test_resolve_phases_mapped_subagent_type(tmp_path):
    (tmp_path / ".kultivait").mkdir()
    (tmp_path / ".kultivait" / "gates.toml").write_text(
        '[subagent."explorer"]\nfrom = "explore"\nto = "plan"\n'
    )
    payload = {"cwd": str(tmp_path), "agent_type": "explorer"}
    assert ambient.resolve_phases("SubagentStop", payload) == ("explore", "plan")
    other = {"cwd": str(tmp_path), "agent_type": "writer"}
    assert ambient.resolve_phases("SubagentStop", other) == ("previous", "next")


def test_resolve_phases_walks_up_to_find_toml(tmp_path):
    (tmp_path / ".kultivait").mkdir()
    (tmp_path / ".kultivait" / "gates.toml").write_text(
        "[precompact]\nfrom = \"build\"\nto = \"verify\"\n"
    )
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert ambient.resolve_phases("PreCompact", {"cwd": str(deep)}) == ("build", "verify")


# ---------- fire(): the safety spine ----------


def test_fire_subagentstop_writes_brief_and_manifest(tmp_path, monkeypatch):
    home = tmp_path / "home"
    payload = subagent_stop_payload(tmp_path)
    ambient.fire(payload, home=home, make_gate=fake_make_gate)
    gate = fake_make_gate.last
    assert gate.calls and gate.calls[0][1] == "previous"  # unmapped -> previous->next
    project = ambient.project_key(payload["cwd"])
    manifest = json.loads(
        (home / ".kultivait" / "briefs" / project / "latest.json").read_text()
    )
    brief = Path(manifest["path"]).read_text()
    assert "kultivait ambient gate" in brief  # provenance header
    assert "FINDINGS" in brief


def test_fire_precompact_reads_main_transcript(tmp_path):
    home = tmp_path / "home"
    tpath = tmp_path / "main.jsonl"
    tpath.write_text(transcript_jsonl(("user", "context pressure")))
    payload = {
        "hook_event_name": "PreCompact",
        "cwd": str(tmp_path),
        "transcript_path": str(tpath),
        "trigger": "auto",
    }
    ambient.fire(payload, home=home, make_gate=fake_make_gate)
    assert "context pressure" in fake_make_gate.last.calls[0][0]


def test_fire_subagentstop_falls_back_to_last_message(tmp_path):
    home = tmp_path / "home"
    payload = subagent_stop_payload(tmp_path, agent_transcript_path="/nonexistent/x.jsonl")
    ambient.fire(payload, home=home, make_gate=fake_make_gate)
    assert fake_make_gate.last.calls[0][0] == "fallback text"


def test_fire_never_raises_even_when_gate_explodes(tmp_path):
    home = tmp_path / "home"
    payload = subagent_stop_payload(tmp_path)

    def bomb():
        raise RuntimeError("gate factory exploded")

    ambient.fire(payload, home=home, make_gate=bomb)  # must not raise
    log = (home / ".kultivait" / "gates.log").read_text()
    assert "SubagentStop" in log


def test_fire_ignores_other_events(tmp_path):
    home = tmp_path / "home"
    invoked = []

    def sentinel():
        invoked.append(True)
        return FakeGate()

    ambient.fire({"hook_event_name": "Stop", "cwd": str(tmp_path)}, home=home,
                 make_gate=sentinel)
    assert not invoked  # Stop is excluded by default — no gate ever constructed


def test_compost_before_distill_is_structural(tmp_path):
    """Gate.distill archives the transcript before any model call (ADR 0019
    durability boundary): a generate that still throws leaves compost on disk."""
    compost = tmp_path / "compost"

    def exploding_generate(prompt: str) -> str:
        raise RuntimeError("model unavailable")

    gate = Gate(generate=exploding_generate, compost_dir=compost)
    with pytest.raises(RuntimeError):
        gate.distill("the transcript", from_phase="a", to_phase="b")
    saved = list(compost.glob("*.txt"))
    assert saved and saved[0].read_text() == "the transcript"


def test_fire_swallow_wraps_distill_failure(tmp_path):
    home = tmp_path / "home"

    class ExplodingGate:
        def distill(self, *a, **k):
            raise RuntimeError("distill blew up mid-flight")

    ambient.fire(subagent_stop_payload(tmp_path), home=home, make_gate=ExplodingGate)
    assert (home / ".kultivait" / "gates.log").exists()  # logged, never raised


# ---------- SessionStart injection ----------


def test_sessionstart_injects_latest_brief(tmp_path, capsys):
    home = tmp_path / "home"
    payload = subagent_stop_payload(tmp_path)
    project = ambient.project_key(payload["cwd"])
    ambient.fire(payload, home=home, make_gate=fake_make_gate)
    ambient.fire(
        {"hook_event_name": "SessionStart", "cwd": payload["cwd"], "source": "compact"},
        home=home,
    )
    out = capsys.readouterr().out
    assert "```" in out and "FINDINGS" in out


def test_sessionstart_silent_without_briefs(tmp_path, capsys):
    ambient.fire({"hook_event_name": "SessionStart", "cwd": str(tmp_path)}, home=tmp_path)
    assert capsys.readouterr().out == ""


# ---------- briefs lane lifecycle ----------


def test_rotation_keeps_last_twenty(tmp_path):
    home = tmp_path / "home"
    project = "rot-test"
    for i in range(24):
        ambient.write_brief(
            home,
            project,
            brief=f"brief {i}",
            from_phase="a",
            to_phase="b",
            event="SubagentStop",
            tokens_before=100,
            tokens_after=10,
        )
    files = sorted((home / ".kultivait" / "briefs" / project).glob("*.md"))
    assert len(files) == ambient.KEEP_BRIEFS
    manifest = json.loads((home / ".kultivait" / "briefs" / project / "latest.json").read_text())
    assert Path(manifest["path"]).exists()


# ---------- install / uninstall ----------


def test_install_claude_writes_hooks_and_scaffold(tmp_path):
    report = ambient.install_claude(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    events = settings["hooks"]
    assert set(events) == {"SubagentStop", "PreCompact", "SessionStart"}
    assert events["SessionStart"][0]["matcher"] == "startup|resume|clear|compact|fork"
    assert events["SubagentStop"][0]["hooks"][0]["async"] is True
    assert (tmp_path / ".kultivait" / "gates.toml").is_file()
    assert "CLAUDE.md" in report


def test_install_claude_idempotent(tmp_path):
    ambient.install_claude(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    ambient.install_claude(tmp_path)
    again = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert again == settings


def test_install_claude_dry_run_changes_nothing(tmp_path):
    report = ambient.install_claude(tmp_path, dry_run=True)
    assert "would" in report
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".kultivait" / "gates.toml").exists()


def test_uninstall_claude_removes_ours_keeps_foreign(tmp_path):
    ambient.install_claude(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    foreign = {"type": "command", "command": "echo foreign"}
    settings["hooks"]["Stop"] = [{"hooks": [foreign]}]
    settings_path.write_text(json.dumps(settings))
    report = ambient.uninstall_claude(tmp_path)
    after = json.loads(settings_path.read_text())
    assert after["hooks"] == {"Stop": [{"hooks": [foreign]}]}
    assert "removed" in report


def test_uninstall_claude_without_settings(tmp_path):
    assert "nothing to uninstall" in ambient.uninstall_claude(tmp_path)


def test_briefs_listing(tmp_path):
    home = tmp_path / "home"
    listing = ambient.briefs_listing(home, tmp_path)
    assert "no briefs" in listing
    payload = subagent_stop_payload(tmp_path)
    ambient.fire(payload, home=home, make_gate=fake_make_gate)
    assert "latest:" in ambient.briefs_listing(home, tmp_path)
