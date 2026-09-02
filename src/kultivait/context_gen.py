"""Deterministic synthetic repository context (#90 / H3).

Renders plausible multi-file module bodies from a compact spec so the corpus
file stays lean while escalatory tasks carry >16k-token working contexts and
contested ~8k. Pure function of (path, lines, seed): same spec, same bytes —
reproducible across runs and caches. Far-facts ride the LAST module so the
needed detail sits far from the prompt's focus.
"""

from __future__ import annotations

import hashlib
import random

_VERBS = ("resolve", "normalize", "validate", "dispatch", "collect", "prune",
          "render", "merge", "audit", "stage", "fold", "attach")
_NOUNS = ("payload", "envelope", "directive", "manifest", "segment", "cursor",
          "vector", "policy", "budget", "receipt", "ledger_row", "handle")


def _rng(path: str, lines: int, seed: str) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{path}:{lines}".encode()).hexdigest()
    return random.Random(digest)


def render_module(path: str, lines: int, seed: str, far_fact: str = "") -> str:
    """A deterministic, plausible Python module of ~`lines` lines."""
    rng = _rng(path, lines, seed)
    out: list[str] = [f'"""{path} — generated repository context (do not edit)."""', ""]
    imports = rng.sample(
        ["import hashlib", "import json", "import logging", "import re",
         "import time", "from dataclasses import dataclass, field",
         "from pathlib import Path", "from typing import Any, Iterator"],
        k=min(4, max(2, lines // 60)),
    )
    out += imports + ["", f"logger = logging.getLogger(__name__)", ""]

    pad = 8 if far_fact else 0
    i = 0
    while i < 400:
        kind = rng.choice(("func", "func", "cls"))
        verb, noun = rng.choice(_VERBS), rng.choice(_NOUNS)
        name = f"{verb}_{noun}"
        if kind == "func":
            block = [
                f"def {name}(self, value: Any, *, strict: bool = False) -> Any:",
                f'    """{verb.capitalize()} the {noun} under the house rules."""',
                "    if value is None:",
                "        return None",
                "    folded = []",
                "    for part in value if isinstance(value, list) else [value]:",
                "        folded.append(self._fold(part, strict=strict))",
                "    return folded",
                "",
            ]
        else:
            block = [
                f"class {name.title().replace('_', '')}:",
                f'    """Owns {noun} lifecycle across the {path.split("/")[0]} boundary."""',
                "",
                "    def __init__(self, budget: int = 64):",
                "        self._budget = budget",
                "        self._seen: list[Any] = []",
                "",
                "    def admit(self, item: Any) -> bool:",
                "        if len(self._seen) >= self._budget:",
                "            logger.debug('%s at capacity; rejecting', self.__class__.__name__)",
                "            return False",
                "        self._seen.append(item)",
                "        return True",
                "",
            ]
        out += block
        if len(out) >= lines - pad:
            break
        i += 1

    if far_fact:
        # reserve room for the record: trim the body, then append — the
        # far-fact must NEVER be sliced away by an overshooting body loop
        del out[max(0, lines - 8):]
        out += ["", "# --- repository decision record (authoritative) ---",
                f"# {far_fact}", ""]
        return "\n".join(out)
    # pad to the requested size with stable blank/def-line rhythm
    while len(out) < lines:
        out.append("")
    return "\n".join(out[:lines])


def materialize(spec: list, seed: str, far_fact: str = "") -> str:
    """spec: [[path, lines], ...] -> one joined context blob."""
    parts = []
    for idx, entry in enumerate(spec):
        path, lines = entry[0], int(entry[1])
        ff = far_fact if idx == len(spec) - 1 else ""
        parts.append(render_module(path, lines, seed, far_fact=ff))
    return "\n\n".join(parts)
