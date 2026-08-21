"""Onboarding completion marker — kultivait's analog of magnitude's
~/.magnitude/state/onboarding.json. `completed` is monotonic: once true it
is never written false. `skipped` records the Esc-skip-for-now path so the
survey panel can nudge the user to re-run init."""

import datetime
import json
from pathlib import Path

ONBOARDING_PATH = Path.home() / ".kultivait" / "onboarding.json"


def is_complete(path: Path = ONBOARDING_PATH) -> bool:
    try:
        return bool(json.loads(Path(path).read_text()).get("completed"))
    except (OSError, ValueError):
        return False


def complete(skipped: bool = False, path: Path = ONBOARDING_PATH) -> None:
    path = Path(path)
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
