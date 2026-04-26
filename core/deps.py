"""
core/deps.py  ─  Vendored dependency manager

Installs third-party packages into  <project_root>/libs/  instead of the
system Python, keeping the project self-contained and shareable without
requiring users to run pip manually.

Usage (optional dependency - graceful degradation on failure):

    from core.deps import require
    edge_tts = require("edge-tts", import_name="edge_tts")
    if edge_tts is None:
        # package unavailable - show a message or disable the feature
        ...

Usage (hard dependency - raises ImportError if it can't be loaded):

    from core.deps import ensure
    ensure("edge-tts", import_name="edge_tts")
"""

import sys
import os
import importlib
import subprocess
import threading

# ── Locate libs/ relative to this file ───────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_LIBS_DIR = os.path.join(os.path.dirname(_HERE), "libs")


def _ensure_libs_on_path():
    os.makedirs(_LIBS_DIR, exist_ok=True)
    if _LIBS_DIR not in sys.path:
        sys.path.insert(0, _LIBS_DIR)


_ensure_libs_on_path()

# Thread lock so parallel tab loads don't double-install the same package
_install_lock = threading.Lock()


def _pip_install(pip_name):
    # type: (str) -> bool
    """
    Install *pip_name* into _LIBS_DIR.
    Returns True on success, False on failure.  Completely silent - no
    console window on Windows.
    """
    # CRITICAL FIX: If running as a compiled PyInstaller .exe, sys.executable 
    # points to the app itself! Do not attempt to pip install, or it will fork bomb.
    if getattr(sys, 'frozen', False):
        return False

    import platform
    creationflags = 0x08000000 if platform.system() == "Windows" else 0
    # Pass user network settings (proxy, etc.) through to pip via env vars.
    try:
        from core import network as _net
        env = _net.subprocess_env()
    except Exception:
        env = None
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "install",
                pip_name,
                "--target={}".format(_LIBS_DIR),
                "--quiet",
                "--disable-pip-version-check",
                "--no-warn-script-location",
            ],
            capture_output=True,
            creationflags=creationflags,
            timeout=120,
            env=env,
        )
        return result.returncode == 0
    except Exception:
        return False


def require(pip_name, import_name=None, auto_install=True):
    # type: (str, str | None, bool) -> object | None
    """
    Try to import *import_name* (defaults to *pip_name* with hyphens → underscores).
    If missing and *auto_install* is True, install into libs/ and retry.
    Returns the module on success, or None on failure.
    """
    if import_name is None:
        import_name = pip_name.replace("-", "_")

    _ensure_libs_on_path()

    # Fast path - already importable
    try:
        importlib.invalidate_caches()
        return importlib.import_module(import_name)
    except ImportError:
        pass

    if not auto_install:
        return None

    # Thread-safe install
    with _install_lock:
        # Double-check after acquiring lock
        try:
            importlib.invalidate_caches()
            return importlib.import_module(import_name)
        except ImportError:
            pass

        if not _pip_install(pip_name):
            return None

        importlib.invalidate_caches()
        try:
            return importlib.import_module(import_name)
        except ImportError:
            return None


def ensure(pip_name, import_name=None):
    # type: (str, str | None) -> object
    """
    Like require() but raises ImportError if the package cannot be loaded.
    Use for hard dependencies where the tab cannot function without them.
    """
    mod = require(pip_name, import_name=import_name)
    if mod is None:
        name = import_name or pip_name.replace("-", "_")
        raise ImportError(
            "Could not import '{}'. "
            "Tried auto-installing '{}' into {} but failed. "
            "Check your internet connection or run:  "
            "pip install {} --target=libs/".format(
                name, pip_name, _LIBS_DIR, pip_name
            )
        )
    return mod


def is_available(pip_name, import_name=None):
    # type: (str, str | None) -> bool
    """
    Non-installing check - returns True only if the package is already present.
    Useful for feature-detection without triggering an install.
    """
    if import_name is None:
        import_name = pip_name.replace("-", "_")
    _ensure_libs_on_path()
    try:
        importlib.invalidate_caches()
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def preinstall_all():
    # type: () -> dict
    """
    Pre-populate libs/ with all optional packages.
    Returns a dict of {pip_name: True/False} results.
    Call from a setup script or first-run wizard.
    """
    packages = [
        ("edge-tts", "edge_tts"),
        ("pyttsx3",  "pyttsx3"),
    ]
    results = {}
    for pip_name, imp_name in packages:
        if is_available(pip_name, imp_name):
            results[pip_name] = True
        else:
            results[pip_name] = _pip_install(pip_name)
    return results