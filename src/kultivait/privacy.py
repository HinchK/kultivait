"""Design-partner privacy primitives (ADR 0025 / the #222 pin).

Everything the route-outcome record needs to stay metadata-only and
pull-only: the active policy version, the persistent per-install salt,
salted repo hashing (never a raw path or name), secret-shape refusal, and
the local redaction audit trail. No network code lives here or anywhere
downstream of it — the export is a file the operator sends themselves.
"""

import hashlib
import json
import re
import secrets
import subprocess
from pathlib import Path

POLICY_VERSION = "v0.5.0-dp"

OUTCOME_LABELS = ("accepted", "retried", "escalated", "wrong_route")

# Curated high-signal credential shapes (the #218 sweep's family, applied at
# retention time): provider keys, PATs, AWS ids, Slack tokens, private-key
# blocks, and assignment-shaped secrets. Matching text is refused outright —
# never stored, never exported.
SECRET_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (
        r"sk-[A-Za-z0-9_-]{16,}",
        r"ghp_[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"xox[bap]-[A-Za-z0-9-]{10,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)\b(password|passwd|secret|api[_-]?key|auth[_-]?token|bearer)\b\s*[:=]\s*\S{8,}",
    )
)


def ensure_install_salt(config_path: Path) -> str:
    """The persistent per-install salt, stored as `install_salt` in the
    config. Generated (and written back) on first need — rewriting the
    machine-generated config is the init path's own behavior."""
    config_path = Path(config_path)
    if config_path.is_file():
        for line in config_path.read_text().splitlines():
            if line.startswith("install_salt"):
                value = line.split("=", 1)[1].strip().strip('"')
                if value:
                    return value
    salt = secrets.token_hex(16)
    _upsert_config_line(config_path, f'install_salt = "{salt}"')
    return salt


def _upsert_config_line(config_path: Path, line: str) -> None:
    """Append or replace a flat `key = value` line in the config, leaving
    every other line byte-identical."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    key = line.split("=", 1)[0].strip()
    lines = config_path.read_text().splitlines() if config_path.is_file() else []
    out, replaced = [], False
    for existing in lines:
        if existing.split("=", 1)[0].strip() == key:
            if not replaced:
                out.append(line)
                replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(line)
    config_path.write_text("\n".join(out) + "\n")


def _git_root(path: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return Path(path).resolve()


def repo_hash_for(path: "str | Path", salt: str) -> str:
    """Salted hash of the repo root (git toplevel, else the resolved cwd).
    The raw path or name never leaves this function."""
    root = _git_root(Path(path))
    return hashlib.sha256(f"{salt}:{root}".encode()).hexdigest()[:16]


def contains_secret_shape(text: "str | None") -> bool:
    if not text:
        return False
    return any(p.search(text) for p in SECRET_PATTERNS)


def record_redaction(entry: dict, redactions_path: "Path | None" = None) -> None:
    """Append a redaction event to the local audit trail — the refusal
    itself is logged even though the text never is."""
    path = Path(redactions_path) if redactions_path else Path.home() / ".kultivait" / "redactions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
