"""
core/i18n.py  -  Internationalisation engine for Quintessential Video Editor

Usage:
    from core.i18n import t, init, get_language, set_language, LANGUAGE_NAMES

    t("cat.cutting")       -> translated category string
    t("tab.crossfader")    -> translated tab name
    t("misc.queue_busy", n=3) -> formatted string with substitution

Call init() once at application startup (before any widgets are created).
Language is persisted in settings.json under the "language" key.
An empty string or missing key triggers auto-detection from the OS locale.
"""

import os
import json
import locale as _locale
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
_LOCALE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "locale",
)

# ── Supported language catalogue ──────────────────────────────────────────────
SUPPORTED_LANGUAGES: list[str] = [
    "en_US", "en_GB",
    "zh_CN", "hi_IN", "es_ES", "ar_MSA", "fr_FR",
    "bn_BD", "pt_BR", "id_ID", "ur_PK",  "ru_RU",
    "de_DE", "ja_JP", "pcm_NG","vi_VN",  "ko_KR",
    "it_IT", "tr_TR", "pl_PL", "nl_NL",  "th_TH",
    "fa_IR", "sw_KE", "tl_PH", "uk_UA",  "ro_RO",
    "ms_MY",
]

# Display names shown in the language selector
LANGUAGE_NAMES: dict[str, str] = {
    "en_US":  "English (US)",
    "en_GB":  "English (British)",
    "zh_CN":  "中文 (普通话)",
    "hi_IN":  "हिन्दी",
    "es_ES":  "Español",
    "ar_MSA": "العربية",
    "fr_FR":  "Français",
    "bn_BD":  "বাংলা",
    "pt_BR":  "Português (Brasil)",
    "id_ID":  "Bahasa Indonesia",
    "ur_PK":  "اردو",
    "ru_RU":  "Русский",
    "de_DE":  "Deutsch",
    "ja_JP":  "日本語",
    "pcm_NG": "Nigerian Pidgin",
    "vi_VN":  "Tiếng Việt",
    "ko_KR":  "한국어",
    "it_IT":  "Italiano",
    "tr_TR":  "Türkçe",
    "pl_PL":  "Polski",
    "nl_NL":  "Nederlands",
    "th_TH":  "ภาษาไทย",
    "fa_IR":  "فارسی",
    "sw_KE":  "Kiswahili",
    "tl_PH":  "Filipino",
    "uk_UA":  "Українська",
    "ro_RO":  "Română",
    "ms_MY":  "Bahasa Melayu",
}

# RTL languages
RTL_LANGUAGES: set[str] = {"ar_MSA", "ur_PK", "fa_IR"}

# ── OS locale → our language code ─────────────────────────────────────────────
_OS_MAP: dict[str, str] = {
    "en_US": "en_US", "en_AU": "en_GB", "en_CA": "en_GB",
    "en_GB": "en_GB", "en_NZ": "en_GB", "en_IE": "en_GB",
    "zh_CN": "zh_CN", "zh_SG": "zh_CN", "zh_TW": "zh_CN",
    "hi_IN": "hi_IN",
    "es_ES": "es_ES", "es_MX": "es_ES", "es_AR": "es_ES",
    "es_CO": "es_ES", "es_CL": "es_ES", "es_PE": "es_ES",
    "ar_SA": "ar_MSA", "ar_EG": "ar_MSA", "ar_AE": "ar_MSA",
    "ar_IQ": "ar_MSA", "ar_MA": "ar_MSA", "ar_DZ": "ar_MSA",
    "fr_FR": "fr_FR", "fr_CA": "fr_FR", "fr_BE": "fr_FR",
    "fr_CH": "fr_FR",
    "bn_BD": "bn_BD", "bn_IN": "bn_BD",
    "pt_BR": "pt_BR", "pt_PT": "pt_BR",
    "id_ID": "id_ID",
    "ur_PK": "ur_PK",
    "ru_RU": "ru_RU", "ru_UA": "ru_RU",
    "de_DE": "de_DE", "de_AT": "de_DE", "de_CH": "de_DE",
    "ja_JP": "ja_JP",
    "vi_VN": "vi_VN",
    "ko_KR": "ko_KR",
    "it_IT": "it_IT", "it_CH": "it_IT",
    "tr_TR": "tr_TR",
    "pl_PL": "pl_PL",
    "nl_NL": "nl_NL", "nl_BE": "nl_NL",
    "th_TH": "th_TH",
    "fa_IR": "fa_IR",
    "sw_KE": "sw_KE", "sw_TZ": "sw_KE",
    "tl_PH": "tl_PH",
    "uk_UA": "uk_UA",
    "ro_RO": "ro_RO",
    "ms_MY": "ms_MY", "ms_SG": "ms_MY",
}

# ── Runtime state ─────────────────────────────────────────────────────────────
_strings:  dict[str, str] = {}
_fallback: dict[str, str] = {}   # always en_US
_current:  str = "en_US"


# ── Private helpers ───────────────────────────────────────────────────────────

def _load_file(code: str) -> dict[str, str]:
    path = os.path.join(_LOCALE_DIR, f"{code}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
                # Strip _meta key - not a translation string
                data.pop("_meta", None)
                return data
        except Exception as exc:
            print(f"[i18n] Failed to load {path}: {exc}")
    return {}


def detect_system_language() -> str:
    """Return the best-matching supported language code for the current OS locale."""
    try:
        sys_loc = _locale.getdefaultlocale()[0] or "en_US"
        if sys_loc in _OS_MAP:
            return _OS_MAP[sys_loc]
        # Language-prefix fallback: "fr" → first fr_XX match
        prefix = sys_loc.split("_")[0]
        for key, val in _OS_MAP.items():
            if key.startswith(prefix + "_"):
                return val
    except Exception:
        pass
    return "en_US"


# ── Public API ────────────────────────────────────────────────────────────────

def get_language() -> str:
    """Return the currently active language code."""
    return _current


def is_rtl() -> bool:
    """Return True if the current language is right-to-left."""
    return _current in RTL_LANGUAGES


def load_language(code: str) -> None:
    """Load *code* as the active language (call this before building any UI)."""
    global _strings, _current, _fallback

    # Always keep en_US as the fallback baseline
    if not _fallback:
        _fallback = _load_file("en_US")

    if code == "en_US":
        _strings = dict(_fallback)
    else:
        data = _load_file(code)
        # Merge: en_US fills any missing keys
        _strings = {**_fallback, **data}

    _current = code


def set_language(code: str) -> None:
    """Persist *code* to settings and reload. Takes effect immediately for
    any t() calls made after this point; existing widgets are not updated
    (a restart is required to re-build all widgets in the new language)."""
    try:
        from core.settings import set as _cfg_set
        _cfg_set("language", code)
    except Exception:
        pass
    load_language(code)


def init() -> None:
    """Initialise i18n at app startup.  Call once before any widgets are built.

    Priority order:
      1. User-saved language in settings.json
      2. OS system locale
      3. Fallback: en_US
    """
    try:
        from core.settings import get as _cfg_get
        saved = _cfg_get("language", "")
    except Exception:
        saved = ""

    if saved and saved in SUPPORTED_LANGUAGES:
        load_language(saved)
    else:
        detected = detect_system_language()
        load_language(detected)
        # Persist detected language so the user can see/change it in settings
        try:
            from core.settings import set as _cfg_set
            _cfg_set("language", detected)
        except Exception:
            pass


def t(key: str, **kwargs) -> str:
    """Return the translated string for *key*.

    Falls back to en_US, then to the bare key if nothing is found.
    Supports Python str.format() substitution via keyword arguments:
        t("misc.queue_busy", n=3)  ->  "Queue: 3 jobs"
    """
    text: str = _strings.get(key) or _fallback.get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except Exception:
            pass
    return text
