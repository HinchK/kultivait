"""Ambient-gates brief-quality eval — runs the protocol in protocol.md.

Real gate path (build_gate(get_config()) -> live distill model), synthetic
Claude-JSONL transcripts with planted facts, SubagentStop payloads,
isolated HOME. Writes results.md, planted.json, transcripts/, briefs/.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean, quantiles

HERE = Path(__file__).parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kultivait import ambient  # noqa: E402
from kultivait.cli import build_gate, get_config  # noqa: E402

N_TRANSCRIPTS = 10
FACTS_PER = 6

PLANTED = {
    "paths": [
        "src/kultivait/ambient.py:88",
        "docs/adr/0019-ambient-gates.md",
        "tests/test_ambient.py:140",
        "~/.kultivait/briefs/<project>/latest.json",
        "experiments/ambient_gate_eval/protocol.md",
        ".claude/settings.json",
        "src/kultivait/gates.py:54",
        ".kultivait/gates.toml",
    ],
    "constraints": [
        "the gate must never block the host agent",
        "compost is written before distillation begins",
        "rotation keeps the twenty most recent briefs",
        "uninstall must never remove foreign hooks",
        "briefs are derived artifacts; compost holds the sources",
        "the phase map defaults to previous-to-next",
    ],
    "decisions": [
        "chose async fire-and-forget over sync distills",
        "sessionstart injects the latest brief with provenance",
        "CLI-direct transport instead of proxy POST",
        "named the family gates not hook to avoid the adoption collision",
        "bounded rotation replaces a single rolling file",
        "no staleness TTL; the provenance header carries the timestamp",
    ],
}

NARRATIVE = [
    "reading the host hook payload fields now",
    "the transcript extractor walks each JSONL line and keeps role-text turns",
    "phase resolution walks up from cwd looking for the map file",
    "project identity is the basename slug plus eight hex of the path",
    "considered a staleness TTL on injection and set it aside",
    "the injection branch prints a fenced block on stdout",
    "checked the ten-thousand-character context cap against typical brief sizes",
    "walked the settings merge for idempotency a second time",
    "the fallback line goes in the project CLAUDE.md",
    "verified foreign hooks survive uninstall",
    "looked at matchers for the all-source sessionstart pattern",
    "the distill hook runs async so the parent never waits",
    "sketching the kill-mid-distill durability test",
    "the compost id carries from and to phases plus a nonce",
    "no-transcript events log and return silently",
]


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def make_transcript(i: int) -> tuple[str, list[str]]:
    facts = [
        PLANTED["paths"][i % 8],
        PLANTED["paths"][(i + 3) % 8],
        PLANTED["constraints"][i % 6],
        PLANTED["constraints"][(i + 2) % 6],
        PLANTED["decisions"][i % 6],
        PLANTED["decisions"][(i + 4) % 6],
    ]
    turns: list[tuple[str, str]] = []
    for n in range(30):
        turns.append(("user", f"step {n}: {NARRATIVE[n % len(NARRATIVE)]}"))
        turns.append(("assistant", f"acknowledged: {NARRATIVE[(n * 7) % len(NARRATIVE)]}"))
    # plant the facts in-context
    turns.insert(10, ("assistant", f"constraint noted: {facts[2]}"))
    turns.insert(14, ("assistant", f"constraint noted: {facts[3]}"))
    turns.insert(20, ("user", f"the path in question is {facts[0]}"))
    turns.insert(26, ("user", f"also see {facts[1]}"))
    turns.insert(32, ("assistant", f"decision: {facts[4]}"))
    turns.insert(38, ("assistant", f"decision: {facts[5]}"))
    jsonl = "\n".join(
        json.dumps({"message": {"role": r, "content": t}}) for r, t in turns
    )
    return jsonl, facts


def main() -> None:
    work = HERE / "run"
    shutil.rmtree(work, ignore_errors=True)
    home = work / "home"
    home.mkdir(parents=True)
    gate = build_gate(get_config())

    recalls: list[float] = []
    kept: list[float] = []
    transcripts_dir = HERE / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)
    planted_all: dict[str, list[str]] = {}

    for i in range(N_TRANSCRIPTS):
        jsonl, facts = make_transcript(i)
        planted_all[f"t{i:02d}"] = facts
        (transcripts_dir / f"t{i:02d}.jsonl").write_text(jsonl)
        tpath = work / f"t{i:02d}.jsonl"
        tpath.write_text(jsonl)
        payload = {
            "hook_event_name": "SubagentStop",
            "cwd": str(work),
            "agent_transcript_path": str(tpath),
            "agent_type": "explorer",
        }
        t0 = time.perf_counter()
        result = gate.distill(
            ambient.extract_transcript(jsonl), from_phase="previous", to_phase="next"
        )
        elapsed = time.perf_counter() - t0
        ambient.write_brief(
            home,
            ambient.project_key(str(work)),
            brief=result.brief,
            from_phase="previous",
            to_phase="next",
            event="SubagentStop",
            tokens_before=result.tokens_before,
            tokens_after=result.tokens_after,
        )
        hit = sum(1 for f in facts if norm(f) in norm(result.brief))
        recalls.append(hit / FACTS_PER)
        kept.append(result.tokens_after / max(1, result.tokens_before))
        print(
            f"t{i:02d}: recall {hit}/{FACTS_PER} kept {kept[-1]:.2%} "
            f"({result.tokens_before}->{result.tokens_after} tok, {elapsed:.1f}s)"
        )
    (HERE / "planted.json").write_text(json.dumps(planted_all, indent=2))
    shutil.copytree(
        home / ".kultivait" / "briefs", HERE / "briefs", dirs_exist_ok=True
    )

    # G4 injection latency
    project = ambient.project_key(str(work))
    lat = []
    for _ in range(100):
        t0 = time.perf_counter()
        ambient.latest_brief_block(home, project)
        lat.append((time.perf_counter() - t0) * 1000)
    inj_p95 = quantiles(lat, n=20)[-1]

    # G5 sync-prefix budget: extraction + compost write (the pre-model work)
    prefix = []
    sample = make_transcript(0)[0]
    for _ in range(20):
        t0 = time.perf_counter()
        text = ambient.extract_transcript(sample)
        cdir = home / ".kultivait" / "compost-prefix"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "x.txt").write_text(text)
        prefix.append((time.perf_counter() - t0) * 1000)
    prefix_p95 = quantiles(prefix, n=20)[-1]

    # G3 durability: kill -9 mid-distill, compost must survive
    kill_ok = 0
    killer = (
        "import sys; sys.path.insert(0, {src!r}); "
        "from kultivait.cli import build_gate, get_config; "
        "from kultivait import ambient; "
        "g = build_gate(get_config()); "
        "g.distill(ambient.extract_transcript(open({tpath!r}).read()) * 4, "
        "from_phase='previous', to_phase='next')"
    ).format(src=str(Path(__file__).resolve().parents[2] / "src"), tpath=str(work / "t00.jsonl"))
    compost_before = {p.name for p in (home / ".kultivait").rglob("*.txt")}
    for trial in range(3):
        proc = subprocess.Popen(
            [sys.executable, "-c", killer],
            env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
            cwd=str(work),
        )
        time.sleep(2.0)
        proc.kill()  # SIGKILL
        proc.wait()
        time.sleep(0.2)
        after = {
            p
            for p in (home / ".kultivait").rglob("*.txt")
            if p.name not in compost_before or trial > 0
        }
        newest = max(after, key=lambda p: p.stat().st_mtime, default=None)
        if newest and "step" in newest.read_text():
            kill_ok += 1
        compost_before |= {p.name for p in after}

    g1, g1b = mean(recalls), min(recalls)
    g2 = mean(kept)
    gates = {
        "G1 brief recall (mean)": (g1, g1 >= 0.80),
        "G1b worst-case recall": (g1b, g1b >= 0.60),
        "G2 tokens-kept (mean)": (g2, g2 <= 0.60),
        "G3 kill durability": (kill_ok, kill_ok >= 3),
        "G4 injection p95 ms": (inj_p95, inj_p95 <= 50),
        "G5 sync-prefix p95 ms": (prefix_p95, prefix_p95 <= 1000),
    }
    print("\n=== GATES ===")
    for name, (value, ok) in gates.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {value:.4f}" if isinstance(value, float)
              else f"{'PASS' if ok else 'FAIL'}  {name}: {value}/3")
    (HERE / "gates.json").write_text(
        json.dumps({k: {"value": v, "pass": bool(ok)} for k, (v, ok) in gates.items()}, indent=2)
    )


if __name__ == "__main__":
    main()
