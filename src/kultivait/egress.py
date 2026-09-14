"""Cloud-egress policy engine (ADR 0025 / Map #221 Phase 1).

Every prospective frontier dispatch passes through here. Postures are
scoped by repository (salted repo_hash — never a raw path), with a global
default; secret-bearing prompts are blocked from egress unconditionally,
before any posture is consulted. The ask-once-per-repo default persists
the operator's answer locally; nothing about this engine transmits.
"""

import json
import time
from pathlib import Path

from kultivait.privacy import contains_secret_shape

POSTURES = ("block", "ask", "allow")

POLICY_PATH = Path.home() / ".kultivait" / "egress_policy.json"
PENDING_PATH = Path.home() / ".kultivait" / "egress_pending.json"

GLOBAL_DEFAULT = "ask"  # the #222 pin: ask-once-per-repo for new repos


def load_policy(path: "Path | None" = None) -> dict:
    path = Path(path) if path else POLICY_PATH
    if not path.is_file():
        return {"global": GLOBAL_DEFAULT, "repos": {}}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {"global": GLOBAL_DEFAULT, "repos": {}}
    data.setdefault("global", GLOBAL_DEFAULT)
    data.setdefault("repos", {})
    return data


def save_policy(policy: dict, path: "Path | None" = None) -> Path:
    path = Path(path) if path else POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy, indent=1))
    return path


def repo_posture(repo_hash: "str | None", policy: dict) -> str:
    if repo_hash and repo_hash in policy.get("repos", {}):
        return policy["repos"][repo_hash]
    return policy.get("global", GLOBAL_DEFAULT)


def set_repo_posture(repo_hash: str, posture: str, path: "Path | None" = None) -> dict:
    if posture not in POSTURES:
        raise ValueError(f"posture must be one of {POSTURES}, got {posture!r}")
    policy = load_policy(path)
    policy.setdefault("repos", {})[repo_hash] = posture
    save_policy(policy, path)
    return policy


def set_global_posture(posture: str, path: "Path | None" = None) -> dict:
    if posture not in POSTURES:
        raise ValueError(f"posture must be one of {POSTURES}, got {posture!r}")
    policy = load_policy(path)
    policy["global"] = posture
    save_policy(policy, path)
    return policy


# ---- pending asks (ask-once-per-repo, answered out-of-band) --------------


def record_pending_ask(repo_hash: str, path: "Path | None" = None) -> None:
    path = Path(path) if path else PENDING_PATH
    pending = load_pending(path)
    pending.setdefault(repo_hash, time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pending, indent=1))


def load_pending(path: "Path | None" = None) -> dict:
    path = Path(path) if path else PENDING_PATH
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def clear_pending(repo_hash: str, path: "Path | None" = None) -> None:
    path = Path(path) if path else PENDING_PATH
    pending = load_pending(path)
    pending.pop(repo_hash, None)
    if pending:
        path.write_text(json.dumps(pending, indent=1))
    elif path.is_file():
        path.unlink()


# ---- the dispatch-time rule (shared by the proxy and the routing eval) ---


def prompt_secret_risk(prompt: "str | None") -> bool:
    """Secret-bearing prompts never egress — checked before any posture."""
    return contains_secret_shape(prompt)


def enforce_prompt_policy(
    prompt: "str | None",
    tier: str,
    *,
    capability_order: list[str],
    local_flags: dict[str, bool],
    policy: dict | None = None,
    repo_hash: "str | None" = None,
    pending_path: "Path | None" = None,
) -> "tuple[str, str]":
    """Returns (serving_tier, cloud_egress_decision).

    Decisions: "local_only" (already local) | "allowed" | "blocked_secret"
    | "blocked_policy" | "ask_local" (degraded locally, ask recorded).
    """
    policy = policy if policy is not None else load_policy()
    if local_flags.get(tier, False):
        return tier, "local_only"
    # degraded secrets serve on the MOST capable local tier: the work is
    # still cloud-worthy, so it gets the best local model available
    local_tiers = [t for t in capability_order if local_flags.get(t, False)]
    local_serve = local_tiers[-1] if local_tiers else capability_order[0]
    if prompt_secret_risk(prompt):
        # unconditional: secrets degrade locally, never egress
        return local_serve, "blocked_secret"
    posture = repo_posture(repo_hash, policy)
    if posture == "block":
        return local_serve, "blocked_policy"
    if posture == "ask":
        if repo_hash:
            record_pending_ask(repo_hash, pending_path)
        return local_serve, "ask_local"
    return tier, "allowed"
