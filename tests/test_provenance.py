"""Session provenance. SPEC.md 3, 14.2, 17.4.

A data file has to trace to the exact software and environment that produced it, so the fields
must be populated for real -- an empty string here would be a silent loss of provenance.
"""

from __future__ import annotations

from pathlib import Path

from tatp import provenance


def test_base_provenance_is_populated():
    base = provenance.base()
    required = {
        "software_version",
        "git_sha",
        "git_dirty",
        "python_version",
        "qt_version",
        "pyside_version",
        "package_versions",
        "platform",
        "hostname",
    }
    assert required <= set(base)
    for key in required - {"screenshot_freeze_sha"}:
        assert base[key], f"{key} is empty"
    assert base["git_dirty"] in ("true", "false")
    assert "PySide6=" in base["package_versions"]


def test_git_sha_is_a_sha_or_empty_never_fabricated():
    sha, dirty = provenance.git_sha()
    assert isinstance(dirty, bool)
    if sha:
        assert len(sha.removesuffix("-dirty")) == 40
        assert sha.endswith("-dirty") == dirty


def test_cloud_sync_is_warned_about_not_refused():
    """SPEC.md 14.1: flag the location, never block the session because of it."""
    markers = ["OneDrive", "Dropbox"]
    assert provenance.cloud_sync_warning(Path("/Users/x/OneDrive/data"), markers)
    assert not provenance.cloud_sync_warning(Path("/Users/x/local/data"), markers)
