"""Learned centroids (ADR 0021): offline recalibration from routing history.

A learned centroid is always a trust-weighted blend with the seed prior at
fixed weight 1.0 — history bends routing, never replaces its foundations.
Nothing here mutates live routing: candidates activate only via the
human-run cutover, and the shadow path is log-only.
"""

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from kultivait.seeds import ROLE_SEEDS

SEED_PRIOR_WEIGHT = 1.0
CLASS_WEIGHTS = {"gold": 1.0, "escalation": 0.75, "silver": 0.5}
MIN_SIGNALS = 10
SILVER_MIN_CHARS = 40
ROLES = list(ROLE_SEEDS)


def table_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".kultivait" / "centroids.json"


def load_table(path: Path | None = None) -> dict:
    path = path or table_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_table(table: dict, path: Path | None = None) -> None:
    path = path or table_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table))


def seat(config_path: Path | None = None) -> dict:
    """[centroids] config seat: active_version / shadow_version."""
    if config_path is None:
        from kultivait.cli import CONFIG_PATH

        config_path = CONFIG_PATH
    try:
        import tomllib

        data = tomllib.loads(Path(config_path).read_text()).get("centroids", {})
    except Exception:
        data = {}
    return {
        "active_version": str(data.get("active_version", "")),
        "shadow_version": str(data.get("shadow_version", "")),
    }


def set_active_version(config_path: Path, version: str) -> None:
    """Surgical config.toml edit: flip [centroids].active_version."""
    path = Path(config_path)
    text = path.read_text() if path.is_file() else ""
    pattern = re.compile(
        r"(\[centroids\][^\[]*?active_version\s*=\s*\")[^\"]*(\")", re.DOTALL
    )
    if pattern.search(text):
        text = pattern.sub(r"\g<1>" + version + r"\g<2>", text, count=1)
    elif "[centroids]" in text:
        text = text.replace("[centroids]", f'[centroids]\nactive_version = "{version}"', 1)
    else:
        text = text.rstrip() + f'\n[centroids]\nactive_version = "{version}"\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _norm(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n else v


def seed_mean(role: str, embed_batch) -> np.ndarray:
    vecs = np.asarray(embed_batch(ROLE_SEEDS[role]), dtype=float)
    vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    return _norm(vecs.mean(axis=0))


def materialize_seeds_v0(embed_batch, path: Path | None = None) -> None:
    table = load_table(path)
    versions = table.setdefault("versions", {})
    if "seeds-v0" in versions:
        return
    versions["seeds-v0"] = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "roles": {
            role: {
                "source": "seeds",
                "vector": seed_mean(role, embed_batch).tolist(),
                "provenance": {"gold": 0, "silver": 0, "escalation": 0,
                               "prior_weight": SEED_PRIOR_WEIGHT},
            }
            for role in ROLES
        },
    }
    table.setdefault("latest", "seeds-v0")
    save_table(table, path)


def _role_for_tier(tier: str, tier_roles: dict) -> str | None:
    if tier in tier_roles:
        return tier_roles[tier]
    if tier.startswith("frontier:"):
        role = tier.split(":", 1)[1]
        return role if role in ROLES else None
    return None


def extract_signals(
    ledger_path: Path, escalations_dir: Path, tier_roles: dict
) -> dict[str, dict[str, list[str]]]:
    """Mine the harvest per the ADR 0021 contract. Text fidelity is honest:
    gold rows carry the best text the ledger retained (snippet); escalations
    carry their archived first user message in full."""
    signals = {r: {"gold": [], "silver": [], "escalation": []} for r in ROLES}
    seen: set[str] = set()

    def _take(key: str, text: str, role: str) -> None:
        text = (text or "").strip()
        if len(text) < SILVER_MIN_CHARS:
            return
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        if digest in seen:
            return
        seen.add(digest)
        signals[role][key].append(text)

    if Path(ledger_path).is_file():
        for line in Path(ledger_path).read_text().splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            role = _role_for_tier(row.get("tier", ""), tier_roles)
            if not role:
                continue
            snippet = row.get("snippet") or ""
            if row.get("toll") == "answered" and row.get("route_choice"):
                chosen = row.get("route_choice")
                chosen_role = _role_for_tier(chosen, tier_roles) or role
                _take("gold", snippet, chosen_role)
            elif row.get("fallback_reason") or row.get("escalation_id"):
                continue  # escalations come from the archive, with full text
            else:
                _take("silver", snippet, role)

    if Path(escalations_dir).is_dir():
        for file in sorted(Path(escalations_dir).glob("esc-*.json")):
            try:
                rec = json.loads(file.read_text())
                messages = rec.get("messages", [])
            except Exception:
                continue
            text = next(
                (m.get("content") or "" for m in reversed(messages)
                 if m.get("role") == "user"),
                "",
            )
            role = _role_for_tier(rec.get("requested_tier", ""), tier_roles)
            if isinstance(text, str) and role is None:
                role = "architect"  # escalations are cloud-worthy by nature
            if role:
                _take("escalation", text if isinstance(text, str) else "", role)
    return signals


def learn(
    embed_batch,
    tier_roles: dict,
    *,
    ledger_path: Path,
    escalations_dir: Path,
    min_signals: int = MIN_SIGNALS,
    path: Path | None = None,
) -> dict:
    """Mine -> blend -> learned-vN candidate table entry. Pure function of
    its inputs; writes the versioned table and returns the new version."""
    path = path or table_path()
    materialize_seeds_v0(embed_batch, path)
    signals = extract_signals(ledger_path, escalations_dir, tier_roles)
    table = load_table(path)
    versions = table.setdefault("versions", {})

    role_entries: dict = {}
    for role in ROLES:
        classes = signals[role]
        total = sum(len(v) for v in classes.values())
        seed_vec = seed_mean(role, embed_batch)
        if total < min_signals:
            role_entries[role] = {
                "source": "seeds",
                "vector": seed_vec.tolist(),
                "provenance": {
                    **{k: len(v) for k, v in classes.items()},
                    "prior_weight": SEED_PRIOR_WEIGHT,
                },
                "note": f"signals {total} < min {min_signals}; seed prior retained",
            }
            continue
        blend = np.asarray(seed_vec, dtype=float) * SEED_PRIOR_WEIGHT
        for cls, texts in classes.items():
            if not texts:
                continue
            vecs = np.asarray(embed_batch(texts), dtype=float)
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            blend = blend + CLASS_WEIGHTS[cls] * _norm(vecs.mean(axis=0))
        role_entries[role] = {
            "source": "learned",
            "vector": _norm(blend).tolist(),
            "provenance": {
                **{k: len(v) for k, v in classes.items()},
                "prior_weight": SEED_PRIOR_WEIGHT,
            },
        }

    n = 1 + max(
        (int(m.group(1)) for v in versions for m in [re.match(r"learned-v(\d+)", v)] if m),
        default=0,
    )
    version = f"learned-v{n}"
    versions[version] = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "roles": role_entries,
    }
    table["latest"] = version
    save_table(table, path)
    return {
        "version": version,
        "roles": {
            r: {"source": e["source"], "provenance": e["provenance"]}
            for r, e in role_entries.items()
        },
    }


def role_vectors(version: str, embed_batch, path: Path | None = None) -> dict | None:
    """{role: vector} for a table version, or None if unavailable."""
    table = load_table(path)
    entry = table.get("versions", {}).get(version)
    if not entry:
        return None
    out = {}
    for role in ROLES:
        row = entry.get("roles", {}).get(role)
        if row and isinstance(row.get("vector"), list) and row["vector"]:
            out[role] = np.asarray(row["vector"], dtype=float)
        else:
            out[role] = seed_mean(role, embed_batch)
    return out


def router_for_version(version: str, config, embed_batch,
                       path: Path | None = None) -> "object | None":
    """A Router whose tier centroids come from a table version."""
    from kultivait.router import Router

    vectors = role_vectors(version, embed_batch, path)
    if vectors is None:
        return None
    centroids = {}
    for tier in config.tiers:
        if tier.role in vectors:
            centroids[tier.name] = vectors[tier.role]
        else:  # eager-default bug guard: never evaluate the fallback needlessly
            centroids[tier.name] = seed_mean(tier.role, embed_batch)
    return Router(centroids=centroids, capability_order=config.capability_order())


# ---------- shadow (log-only dual classification) ----------

_shadow_cache: dict = {}


def shadow_router(config=None, embed_batch=None):
    """Lazy candidate router from the seat's shadow_version; cached."""
    from kultivait.cli import CONFIG_PATH, get_config

    conf = seat(CONFIG_PATH)
    version = conf.get("shadow_version", "")
    if not version:
        return None
    cache_key = version
    if _shadow_cache.get(cache_key) is not None:
        return _shadow_cache[cache_key]
    cfg = config or get_config()
    router = router_for_version(version, cfg, embed_batch)
    _shadow_cache[cache_key] = router
    return router


def maybe_shadow_classify(vec, incumbent_decision, fingerprint: str = "",
                          *, config=None, embed_batch=None,
                          log_path: Path | None = None) -> None:
    """Dual-classify the already-computed vector; log-only, never raises."""
    try:
        candidate = shadow_router(config=config, embed_batch=embed_batch)
        if candidate is None:
            return
        cd = candidate.classify(vec)
        if cd.tier == incumbent_decision.tier and cd.escalated == incumbent_decision.escalated:
            return  # agreement is not interesting enough to log
        from kultivait.distill.shadow import ShadowRecord, append_shadow_log

        append_shadow_log(
            ShadowRecord(
                ts=time.time(),
                fingerprint=fingerprint,
                prompt_hash="",
                incumbent={"kind": "centroid", "tier": incumbent_decision.tier,
                           "margin": incumbent_decision.margin,
                           "escalated": incumbent_decision.escalated},
                shadow={"kind": "centroid", "tier": cd.tier,
                        "margin": cd.margin, "escalated": cd.escalated},
                agree=False,
            ),
            log_path,
        )
    except Exception:
        return  # the shadow never disturbs the live path


def shadow_stats(log_path: Path | None = None) -> dict:
    """Centroid-shadow disagreement counts for `centroids status`."""
    from kultivait.distill.shadow import _default_log_path

    path = log_path or _default_log_path()
    rows = []
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if (rec.get("incumbent") or {}).get("kind") == "centroid":
                rows.append(rec)
    return {"disagreements": len(rows)}
