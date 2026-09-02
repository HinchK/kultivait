"""Z3 (#121): IDE auto-patcher — detect + patch IDE configs for proxy routing."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

# (ide_name, settings_path_suffix, key_settings)
# key_settings: {json_key: value_template} where {base} is the proxy URL
IDE_REGISTRY = {
    "cursor": {
        "paths": {
            "darwin": "~/Library/Application Support/Cursor/User/settings.json",
            "linux": "~/.config/Cursor/User/settings.json",
        },
        "keys": {
            "openai.baseUrl": "{base}/v1",
        },
    },
    "vscode": {
        "paths": {
            "darwin": "~/Library/Application Support/Code/User/settings.json",
            "linux": "~/.config/Code/User/settings.json",
        },
        "keys": {
            "openai.baseUrl": "{base}/v1",
        },
    },
    "windsurf": {
        "paths": {
            "darwin": "~/.codeium/windsurf/settings.json",
            "linux": "~/.codeium/windsurf/settings.json",
        },
        "keys": {
            "openai.baseUrl": "{base}/v1",
        },
    },
}

BACKUP_SUFFIX = ".kultivait-bak"


def detect_ide(ide: str, platform: str = "darwin") -> "Path | None":
    """Return the settings.json path for the named IDE, or None if not found."""
    spec = IDE_REGISTRY.get(ide)
    if not spec:
        return None
    rel = spec["paths"].get(platform) or spec["paths"].get("darwin")
    if not rel:
        return None
    p = Path(rel).expanduser()
    return p if p.exists() else None


def detect_all(platform: str = "darwin") -> dict:
    """Detect all installed IDEs; return {name: path}."""
    out = {}
    for name in IDE_REGISTRY:
        p = detect_ide(name, platform)
        if p:
            out[name] = p
    return out


def patch_ide(
    ide: str,
    settings_path: Path,
    base_url: str,
    *,
    dry_run: bool = False,
) -> dict:
    """Patch the IDE's settings.json to route through the proxy.

    Returns {"patched": bool, "keys_set": [...], "backup": str | None, "dry_run": bool}.
    """
    spec = IDE_REGISTRY[ide]
    data = json.loads(settings_path.read_text())
    original = json.dumps(data, indent=2)

    keys_set = []
    for dotted_key, template in spec["keys"].items():
        val = template.format(base=base_url)
        # support dotted keys by nesting
        parts = dotted_key.split(".")
        d = data
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        if d.get(parts[-1]) != val:
            d[parts[-1]] = val
            keys_set.append(dotted_key)

    if not keys_set:
        return {"patched": False, "keys_set": [], "backup": None, "dry_run": dry_run}

    backup_path = settings_path.parent / (settings_path.name + BACKUP_SUFFIX)

    if dry_run:
        return {"patched": True, "keys_set": keys_set, "backup": str(backup_path), "dry_run": True}

    # atomic write: backup first, then write
    if settings_path.exists():
        shutil.copy2(settings_path, backup_path)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(settings_path)

    return {"patched": True, "keys_set": keys_set, "backup": str(backup_path), "dry_run": False}


def restore_ide(settings_path: Path) -> bool:
    """Restore from backup if it exists."""
    backup = settings_path.parent / (settings_path.name + BACKUP_SUFFIX)
    if not backup.exists():
        return False
    shutil.copy2(backup, settings_path)
    backup.unlink()
    return True
