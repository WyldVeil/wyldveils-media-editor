"""
tests/test_core.py  -  Tests for core utilities (no GUI required).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_app_version_format():
    """APP_VERSION is a semantic version string."""
    from core import APP_VERSION
    parts = APP_VERSION.split(".")
    assert len(parts) == 3, f"Expected major.minor.patch, got: {APP_VERSION}"
    assert all(p.isdigit() for p in parts), f"Non-numeric version parts: {APP_VERSION}"


def test_core_imports():
    """Core submodules import without error."""
    import core.hardware
    import core.settings
    import core.skins
    assert True


def test_settings_roundtrip(tmp_path, monkeypatch):
    """load_settings returns defaults when no file exists; save_settings is idempotent."""
    from core import settings as s
    fake_path = str(tmp_path / "settings.json")
    monkeypatch.setattr(s, "_SETTINGS_PATH", fake_path)

    data = s.load_settings()
    assert isinstance(data, dict)

    s.save_settings(data)
    reloaded = s.load_settings()
    assert reloaded == data
