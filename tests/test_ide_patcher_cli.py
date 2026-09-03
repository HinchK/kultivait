"""Z3 (#121) tests: IDE auto-patcher — detect, patch, backup, rollback, dry-run."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from kultivait.hook.ide import (
    BACKUP_SUFFIX,
    detect_ide,
    patch_ide,
    restore_ide,
)


@pytest.fixture
def fake_ide(tmp_path: Path):
    """A fake Cursor settings.json."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"editor.fontSize": 14}))
    return settings


# ---------------------------------------------------------------- detection


def test_detect_ide_returns_path_or_none():
    """detect_ide returns a Path or None for a known/unknown IDE."""
    p = detect_ide("cursor", "darwin")
    assert p is None or isinstance(p, Path)


def test_detect_unknown_ide():
    assert detect_ide("nonexistent-ide", "darwin") is None


# ---------------------------------------------------------------- patching


def test_patch_sets_base_url(fake_ide):
    result = patch_ide("cursor", fake_ide, "http://localhost:4114")
    assert result["patched"] is True
    assert "openai.baseUrl" in result["keys_set"]
    data = json.loads(fake_ide.read_text())
    assert data["openai"]["baseUrl"] == "http://localhost:4114/v1"


def test_patch_preserves_existing_keys(fake_ide):
    result = patch_ide("cursor", fake_ide, "http://localhost:4114")
    assert result["patched"] is True
    data = json.loads(fake_ide.read_text())
    assert "openai" in data  # the new key landed
    assert data.get("editor.fontSize") == 14  # original survives


def test_patch_creates_backup(fake_ide):
    result = patch_ide("cursor", fake_ide, "http://localhost:4114")
    backup = Path(result["backup"])
    assert backup.exists()
    assert backup.name == "settings.json" + BACKUP_SUFFIX
    original = json.loads(backup.read_text())
    assert original.get("editor.fontSize") == 14


def test_patch_idempotent_no_change(fake_ide):
    patch_ide("cursor", fake_ide, "http://localhost:4114")
    result = patch_ide("cursor", fake_ide, "http://localhost:4114")
    assert result["patched"] is False  # already routed
    assert result["keys_set"] == []


# ---------------------------------------------------------------- dry-run


def test_dry_run_does_not_write(fake_ide):
    original = fake_ide.read_text()
    result = patch_ide("cursor", fake_ide, "http://localhost:4114", dry_run=True)
    assert result["dry_run"] is True
    assert result["patched"] is True
    assert fake_ide.read_text() == original  # unchanged
    assert not (fake_ide.parent / (fake_ide.name + BACKUP_SUFFIX)).exists()


# ---------------------------------------------------------------- restore


def test_restore_from_backup(fake_ide):
    patch_ide("cursor", fake_ide, "http://localhost:4114")
    assert restore_ide(fake_ide) is True
    data = json.loads(fake_ide.read_text())
    assert "openai" not in data or "baseUrl" not in data.get("openai", {})
    assert data.get("editor.fontSize") == 14  # original restored


def test_restore_no_backup(fake_ide):
    assert restore_ide(fake_ide) is False


# ---------------------------------------------------------------- atomicity


def test_atomic_write_no_partial(fake_ide):
    """The tmp-then-replace pattern leaves no .tmp files."""
    patch_ide("cursor", fake_ide, "http://localhost:4114")
    tmps = list(fake_ide.parent.glob("*.tmp"))
    assert not tmps
    # the settings file is valid JSON
    json.loads(fake_ide.read_text())
