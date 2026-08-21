"""Onboarding completion marker — kultivait's analog of magnitude's
~/.magnitude/state/onboarding.json. `completed` is monotonic: once true it
is never written false. `skipped` records the Esc-skip-for-now path so the
survey panel can nudge the user to re-run init."""

import datetime
import json
from pathlib import Path

ONBOARDING_PATH = Path.home() / ".kultivait" / "onboarding.json"


def _resolve(path: "Path | None") -> Path:
    # resolved at call time (not as a def-time default) so tests can point
    # the whole module at a tmp dir by patching ONBOARDING_PATH
    return Path(path) if path is not None else ONBOARDING_PATH


def is_complete(path: "Path | None" = None) -> bool:
    try:
        return bool(json.loads(_resolve(path).read_text()).get("completed"))
    except (OSError, ValueError):
        return False


def complete(skipped: bool = False, path: "Path | None" = None) -> None:
    path = _resolve(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "completed": True,
                "completed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "skipped": skipped,
            },
            indent=2,
        )
        + "\n"
    )
