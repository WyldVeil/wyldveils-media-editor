"""
core/settings.py  ─  Centralised application settings
Single source of truth for reading and writing settings.json.
Both SettingsTab and AdvancedSettingsTab import from here, eliminating
the previously duplicated load/save logic found in each tab.

Usage:
    from core.settings import load_settings, save_settings, SETTINGS_FILE
"""

import os
import json

# ── File location ─────────────────────────────────────────────────────────────
SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "settings.json",
)

# ── Default values ────────────────────────────────────────────────────────────
_DEFAULTS = {
    "default_crf":            "18",
    "default_preset":         "fast",
    "default_audio_bitrate":  "192k",
    "ffmpeg_path_override":   "",
    "default_output_folder":  "",
    "auto_open_output":       False,
    "theme":                  "Classic",
    "star_speed":             1.0,
    "star_count":             55,
    "language":               "",
}


def load_settings():
    # type: () -> dict
    """
    Return a settings dict merged on top of defaults.
    Never raises - falls back to defaults silently on any I/O or parse error.
    """
    result = dict(_DEFAULTS)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                result.update(json.load(f))
    except json.JSONDecodeError as exc:
        print(f"[Settings] settings.json is corrupt and will be ignored: {exc}")
    except Exception as exc:
        print(f"[Settings] Could not load settings: {exc}")
    return result


def save_settings(data):
    # type: (dict) -> bool
    """
    Persist *data* to settings.json.
    Returns True on success, False on failure.
    """
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as exc:
        print("[Settings] Save error: {}".format(exc))
        return False


def get(key, fallback=None):
    """Convenience one-liner: load → get key → fallback."""
    return load_settings().get(key, fallback)


def set(key, value):
    """Convenience one-liner: load → update key → save."""
    data = load_settings()
    data[key] = value
    save_settings(data)
