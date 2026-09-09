"""Ambient gates: phase-gates fired by agent-framework hooks (ADR 0019).

The never-block rule is absolute: every code path either does its work
silently or logs to ~/.kultivait/gates.log and exits clean. A gate may not
block, fail, or stall the host under any circumstance.
"""

import hashlib
import json
import sys
import time
import traceback
from pathlib import Path

GATES_LOG = "gates.log"
BRIEFS_DIRNAME = "briefs"
GATES_TOML = "gates.toml"
FIRE_COMMAND = "kultivait gates fire"
KEEP_BRIEFS = 20

INSTALL_CLAUDE_HOOKS = {
    "SubagentStop": [
        {"hooks": [{"type": "command", "command": FIRE_COMMAND, "async": True, "timeout": 300}]}
    ],
    "PreCompact": [
        {"hooks": [{"type": "command", "command": FIRE_COMMAND, "async": True, "timeout": 300}]}
    ],
    "SessionStart": [
        {
            "matcher": "startup|resume|clear|compact|fork",
            "hooks": [{"type": "command", "command": FIRE_COMMAND, "timeout": 10}],
        }
    ],
}

CLAUDE_MD_FALLBACK = (
    "Phase context lives in ~/.kultivait/briefs/ — read the latest brief "
    "before starting a new phase."
)

GATES_TOML_TEMPLATE = """\
# kultivait ambient-gates phase map — unmapped events default to previous -> next
# Map subagent types (SubagentStop) or set global PreCompact phases.
#
# [subagent."explorer"]
# from = "explore"
# to = "plan"
#
# [precompact]
# from = "previous"
# to = "next"
"""


def project_key(cwd: str) -> str:
    """Stable project identity: basename slug + 8 hex of the absolute path."""
    path = Path(cwd).resolve()
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in path.name).strip("-")
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    return f"{slug or 'project'}-{digest}"


def _find_gates_toml(cwd: str) -> Path | None:
    current = Path(cwd).resolve()
    for candidate in [current, *current.parents]:
        toml = candidate / ".kultivait" / GATES_TOML
        if toml.is_file():
            return toml
    return None


def resolve_phases(event: str, payload: dict) -> tuple[str, str]:
    """Map event context -> (from_phase, to_phase); default previous -> next."""
    from_phase, to_phase = "previous", "next"
    toml = _find_gates_toml(payload.get("cwd", "."))
    if toml is None:
        return from_phase, to_phase
    try:
        import tomllib

        data = tomllib.loads(toml.read_text())
    except Exception:
        return from_phase, to_phase
    section = None
    if event == "SubagentStop":
        section = (data.get("subagent") or {}).get(payload.get("agent_type") or "")
    elif event == "PreCompact":
        section = data.get("precompact")
    if isinstance(section, dict):
        from_phase = str(section.get("from", from_phase))
        to_phase = str(section.get("to", to_phase))
    return from_phase, to_phase


def extract_transcript(jsonl_text: str) -> str:
    """Extract role:text turns from a Claude Code transcript JSONL."""
    turns: list[str] = []
    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        text = "\n".join(t for t in texts if t)
        if text:
            turns.append(f"{role}: {text}")
    return "\n\n".join(turns)


def _select_transcript(payload: dict) -> str | None:
    """Pick the transcript source for a firing event; None when there is none."""
    event = payload.get("hook_event_name", "")
    if event == "SubagentStop":
        path = payload.get("agent_transcript_path")
        if path:
            try:
                return extract_transcript(Path(path).read_text())
            except Exception:
                pass
        return payload.get("last_assistant_message") or None
    if event == "PreCompact":
        path = payload.get("transcript_path")
        if path:
            try:
                return extract_transcript(Path(path).read_text())
            except Exception:
                return None
    return None


def _briefs_dir(home: Path, project: str) -> Path:
    return home / ".kultivait" / BRIEFS_DIRNAME / project


def _log(home: Path, message: str) -> None:
    try:
        log = home / ".kultivait" / GATES_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
    except Exception:
        pass


def write_brief(
    home: Path,
    project: str,
    *,
    brief: str,
    from_phase: str,
    to_phase: str,
    event: str,
    tokens_before: int,
    tokens_after: int,
) -> Path:
    """Write a numbered brief, rotate to KEEP_BRIEFS, refresh latest.json."""
    directory = _briefs_dir(home, project)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    existing = sorted(p for p in directory.glob("*.md"))
    seq = len(existing) + 1
    path = directory / f"{seq:03d}-{from_phase}_to_{to_phase}-{stamp}.md"
    header = (
        f"> kultivait ambient gate · {from_phase} → {to_phase} · "
        f"{time.strftime('%Y-%m-%dT%H:%M:%S')} · {tokens_before}→{tokens_after} tok · "
        f"source: {event}\n\n"
    )
    path.write_text(header + brief)
    manifest = {
        "path": str(path),
        "from": from_phase,
        "to": to_phase,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
    }
    (directory / "latest.json").write_text(json.dumps(manifest, indent=2))
    for stale in sorted(directory.glob("*.md"))[:-KEEP_BRIEFS]:
        stale.unlink()
    return path


def latest_brief_block(home: Path, project: str) -> str | None:
    """The latest brief as a fenced block with provenance, for SessionStart."""
    manifest_path = _briefs_dir(home, project) / "latest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
        brief = Path(manifest["path"]).read_text()
    except Exception:
        return None
    return f"```\n{brief.strip()}\n```\n"


def fire(payload: dict, *, home: Path | None = None, make_gate=None) -> None:
    """The gates-fire core. Never raises; every failure logs and returns."""
    home = home or Path.home()

    def safe(note: str) -> None:
        _log(home, f"{note}: {traceback.format_exc(limit=2).splitlines()[-1]}")

    try:
        event = payload.get("hook_event_name", "")
        project = project_key(payload.get("cwd", "."))
    except Exception:
        safe("bad-payload")
        return

    if event == "SessionStart":
        try:
            block = latest_brief_block(home, project)
            if block:
                sys.stdout.write(block)
        except Exception:
            safe("sessionstart-inject")
        return

    if event not in ("SubagentStop", "PreCompact"):
        return

    try:
        from_phase, to_phase = resolve_phases(event, payload)
        transcript = _select_transcript(payload)
        if not transcript or not transcript.strip():
            _log(home, f"{event}: no-transcript project={project}")
            return
        gate = make_gate() if make_gate else _default_gate()
        # Gate.distill composts the transcript synchronously BEFORE any model
        # call (gates.py invariant) — the durability boundary for async kills.
        result = gate.distill(transcript, from_phase=from_phase, to_phase=to_phase)
        write_brief(
            home,
            project,
            brief=result.brief,
            from_phase=from_phase,
            to_phase=to_phase,
            event=event,
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
        )
    except Exception:
        safe(event or "fire")


def _default_gate():
    from kultivait.cli import build_gate, get_config

    return build_gate(get_config())


# ---------- install / uninstall (Claude Code adapter) ----------


def _claude_settings_path(project_dir: Path) -> Path:
    return project_dir / ".claude" / "settings.json"


def _hook_is_ours(hook: dict) -> bool:
    return FIRE_COMMAND in str(hook.get("command", ""))


def install_claude(project_dir: Path, *, dry_run: bool = False) -> str:
    """Merge our hooks into project .claude/settings.json + scaffold gates.toml."""
    settings_path = _claude_settings_path(project_dir)
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text())
        except Exception:
            settings = {}
    hooks = settings.setdefault("hooks", {})
    changed: list[str] = []
    for event, groups in INSTALL_CLAUDE_HOOKS.items():
        existing_groups = hooks.setdefault(event, [])
        already = any(
            _hook_is_ours(hook) for group in existing_groups for hook in group.get("hooks", [])
        )
        if not already:
            existing_groups.append(json.loads(json.dumps(groups[0])))
            changed.append(event)
    gates_toml = project_dir / ".kultivait" / GATES_TOML
    scaffold = not gates_toml.is_file()
    report_lines = [f"would update {settings_path}" if dry_run else f"updated {settings_path}"]
    for event in changed:
        report_lines.append(f"  {'+' if not dry_run else ' '} {event}: {FIRE_COMMAND}")
    report_lines.append(
        (f"{'would scaffold' if dry_run else 'scaffolded'} {gates_toml}")
        if scaffold
        else f"kept existing {gates_toml}"
    )
    if not dry_run:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
        if scaffold:
            gates_toml.parent.mkdir(parents=True, exist_ok=True)
            gates_toml.write_text(GATES_TOML_TEMPLATE)
    report_lines.append(f"fallback instruction for CLAUDE.md: {CLAUDE_MD_FALLBACK}")
    return "\n".join(report_lines)


def uninstall_claude(project_dir: Path) -> str:
    """Remove exactly our hook entries; foreign hooks are untouched."""
    settings_path = _claude_settings_path(project_dir)
    if not settings_path.is_file():
        return f"no {settings_path} — nothing to uninstall"
    try:
        settings = json.loads(settings_path.read_text())
    except Exception:
        return f"unreadable {settings_path} — leaving untouched"
    hooks = settings.get("hooks", {})
    removed: list[str] = []
    for event, groups in list(hooks.items()):
        kept_groups = []
        for group in groups:
            hook_list = group.get("hooks", [])
            ours = [h for h in hook_list if _hook_is_ours(h)]
            if ours:
                removed.append(event)
            foreign = [h for h in hook_list if not _hook_is_ours(h)]
            if foreign:
                kept_groups.append({**group, "hooks": foreign})
        if kept_groups:
            hooks[event] = kept_groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    if removed:
        return f"removed {FIRE_COMMAND} from: {', '.join(sorted(set(removed)))}"
    return "no kultivait gates hooks found"


def briefs_listing(home: Path, project_dir: Path) -> str:
    directory = _briefs_dir(home, project_key(str(project_dir)))
    files = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not files:
        return f"no briefs for {directory}"
    lines = [f"briefs — {directory} (newest last)"]
    lines.extend(f"  {p.name}" for p in files[-KEEP_BRIEFS :])
    manifest = directory / "latest.json"
    if manifest.is_file():
        lines.append(f"latest: {manifest.read_text().strip()}")
    return "\n".join(lines)
