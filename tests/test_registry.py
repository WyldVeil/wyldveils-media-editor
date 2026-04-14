"""
tests/test_registry.py  -  Structural tests for the tab registry.

These tests verify the registry is internally consistent and complete
without launching any GUI (no Tk required).
"""
import sys
import os
import importlib
import pytest

# Ensure project root is on path when running with pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_registry_imports():
    """Registry module imports without error."""
    from tabs.registry import TOOLS, PINNED, HIDDEN
    assert TOOLS is not None
    assert PINNED is not None
    assert HIDDEN is not None


def test_pinned_structure():
    """PINNED is a (str, class) tuple."""
    from tabs.registry import PINNED
    assert isinstance(PINNED, tuple) and len(PINNED) == 2
    name, cls = PINNED
    assert isinstance(name, str) and len(name) > 0
    assert isinstance(cls, type)


def test_hidden_structure():
    """HIDDEN is a dict mapping str → class."""
    from tabs.registry import HIDDEN
    assert isinstance(HIDDEN, dict)
    for name, cls in HIDDEN.items():
        assert isinstance(name, str)
        assert isinstance(cls, type)


def test_tools_structure():
    """TOOLS has 6 categories, each with a non-empty list of (name, class) tuples."""
    from tabs.registry import TOOLS
    assert len(TOOLS) == 6, f"Expected 6 categories, got {len(TOOLS)}"
    for category, items in TOOLS.items():
        assert isinstance(items, list) and len(items) > 0, f"Empty category: {category}"
        for entry in items:
            name, cls = entry
            assert isinstance(name, str) and len(name) > 0
            assert isinstance(cls, type), f"{name!r} is not a class"


def test_no_duplicate_tool_names():
    """No two tools share the same display name."""
    from tabs.registry import TOOLS
    names = [name for items in TOOLS.values() for name, _ in items]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"Duplicate tool names: {duplicates}"


def test_no_duplicate_tab_classes():
    """No tab class appears more than once across all categories."""
    from tabs.registry import TOOLS
    classes = [cls for items in TOOLS.values() for _, cls in items]
    duplicates = {c.__name__ for c in classes if classes.count(c) > 1}
    assert not duplicates, f"Duplicate tab classes: {duplicates}"


def test_tool_count():
    """Total tool count matches expected (73 tools across 6 categories)."""
    from tabs.registry import TOOLS
    total = sum(len(items) for items in TOOLS.values())
    assert total == 73, f"Expected 73 tools, got {total}"


def test_sub_package_imports():
    """All sub-packages import cleanly."""
    packages = [
        "tabs.cutting",
        "tabs.social",
        "tabs.audio",
        "tabs.transcoder",
        "tabs.visuals",
        "tabs.system",
    ]
    for pkg in packages:
        mod = importlib.import_module(pkg)
        assert mod is not None, f"Failed to import {pkg}"


def test_compatibility_shims():
    """Old tabs.tab_* import paths still resolve (backward compatibility)."""
    shim_checks = [
        ("tabs.tab_crossfader", "CrossfaderTab"),
        ("tabs.tab_youtubedownloader", "YouTubeDownloaderTab"),
        ("tabs.tab_resolutionscaler", "ResolutionScalerTab"),
        ("tabs.tab_fpsinterpolator", "FPSInterpolatorTab"),
        ("tabs.tab_screenrecorder", "ScreenRecorderTab"),
        ("tabs.tab_allinone", "AllInOneTab"),
    ]
    for module_path, class_name in shim_checks:
        mod = importlib.import_module(module_path)
        assert hasattr(mod, class_name), f"{module_path} missing {class_name}"
