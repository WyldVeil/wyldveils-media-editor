"""
i18n_audit_fix.py  --  Automatically find hardcoded UI strings in tab Python
files, replace them with t() calls, and add new keys to en_US.json.

Run:
    python i18n_audit_fix.py --dry-run   # preview only
    python i18n_audit_fix.py             # apply changes

After running, execute translate_missing.py to fill in all other languages.
"""

import re
import json
import sys
import argparse
from pathlib import Path

ROOT       = Path(__file__).parent
LOCALE_DIR = ROOT / "locale"
TABS_DIR   = ROOT / "tabs"

# ── Heuristics: strings to SKIP (keep as-is) ──────────────────────────────────
SKIP_PATTERNS = [
    re.compile(r'^\s*$'),                         # blank / whitespace only
    re.compile(r'^[\d\s×xX:.\-/\\%+]+$'),         # numbers, dimensions like "1920×1080"
    re.compile(r'^[A-Z0-9_]{2,}$'),               # ALL_CAPS constants
    re.compile(r'\{[^}]+\}'),                     # contains {placeholder}
    re.compile(r'^[-–-·•▸▶◀★✓✗⚠]+\s*$'),         # pure symbol strings
    re.compile(r'\.(mp4|mkv|mov|avi|webm|flv|m4v|wav|mp3|aac|flac|ogg|srt|ass|ssa|vtt|txt|png|jpg|jpeg|gif|webp|cube|3dl|rnnn?)(\s|$)', re.I),
    re.compile(r'^(libx264|libx265|libsvtav1|vp9|vp8|hevc|h264|h265|av1|aac|mp3|flac|wav|opus|pcm|yuv|nv12|bgr|rgb|nvenc|amf|vaapi|qsv|cuda|opencl|metal|auto|none|copy|default)', re.I),
    re.compile(r'^(hstack|vstack|grid|wipe|mix|none|replace|strip)$', re.I),  # internal enum values
    re.compile(r'^[A-Za-z0-9_\-]+\.(py|json|txt|log|exe|dll|so)$'),          # filenames
    re.compile(r'^(Alt|Ctrl|Shift)\+'),                                        # hotkeys
    re.compile(r'^[A-Za-z0-9\-_]+$'),             # single word, no spaces → likely a technical id
    re.compile(r'^pip install\s'),                 # pip commands
    re.compile(r'^\d+\s*Hz$', re.I),              # frequencies like "1000 Hz"
    re.compile(r'^[A-Z]{2,}/[A-Z]{2,}$'),         # like "SRT/ASS"
]

# These strings look like words but are actually technical / universal
SKIP_EXACT = {
    "", " ", "…", "·", "×", "↑", "↓", "←", "→", "↔", "↕",
    "OK", "FFmpeg", "yt-dlp", "ffmpeg", "ffprobe", "ffplay",
    "CRF", "FPS", "fps", "Hz", "dB", "px", "MB", "GB", "KB",
    "LUFS", "LRA", "TP", "EBU", "R128",
    "MP4", "MKV", "MOV", "AVI", "WEBM", "GIF", "WebM",
    "MP3", "AAC", "WAV", "FLAC", "OGG",
    "SRT", "ASS", "SSA", "VTT",
    "PNG", "JPG", "JPEG",
    "TFF", "BFF",
    "VP9", "VP8", "H.264", "H.265", "HEVC", "AV1",
    "SMPTE",
    "EQ", "LUT",
    "W:", "H:", "X:", "Y:", "#",
    "→", "←", "▶", "⏸", "⏭", "⏹",
    "In:", "Out:",   # waveform labels that are very short
    "dB",
    "RGB", "YUV",
    "HQDN3D", "NLMeans",
    "arnndn", "anlmdn", "afftdn",
    "TikTok", "YouTube", "Instagram", "Twitter", "Facebook",
    "Snapchat", "LinkedIn",
    "Ken Burns",
    "EBU R128",
}


def should_skip(s: str) -> bool:
    s = s.strip()
    if s in SKIP_EXACT:
        return True
    if len(s) < 3:
        return True
    for pat in SKIP_PATTERNS:
        if pat.search(s):
            return True
    return False


def make_key(module: str, text: str) -> str:
    """Generate a locale key like  module.some_label_text"""
    slug = text.lower().strip()
    # Remove leading emoji / symbols
    slug = re.sub(r'^[^\w\s]+\s*', '', slug)
    # Keep only alphanumeric + spaces
    slug = re.sub(r'[^\w\s]', ' ', slug)
    slug = slug.strip()
    # Collapse whitespace → underscores
    slug = re.sub(r'\s+', '_', slug)
    # Truncate
    slug = slug[:48].rstrip('_')
    if not slug:
        slug = "item"
    return f"{module}.{slug}"


def load_en() -> dict:
    with open(LOCALE_DIR / "en_US.json", encoding="utf-8") as f:
        d = json.load(f)
    d.pop("_meta", None)
    return d


def save_en(data: dict) -> None:
    path = LOCALE_DIR / "en_US.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    meta = raw.get("_meta")
    out = {}
    if meta:
        out["_meta"] = meta
    out.update(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


# ─── Pattern matchers ─────────────────────────────────────────────────────────

# text="..." or text='...' NOT already a t( call
# We look for: text=  then optional space then quote then content
_TEXT_ARG_RE = re.compile(
    r'''(?<!\w)text\s*=\s*(?!t\()(?!f['"]) # not already t() and not f-string
        (?P<q>["\'])(?P<val>(?:[^"'\\]|\\.)*)(?P=q)''',
    re.VERBOSE,
)

# values=["a", "b", ...] in combobox / OptionMenu
# captures the entire list literal
_VALUES_RE = re.compile(
    r'''values\s*=\s*\[(?P<items>[^\]]+)\]''',
    re.DOTALL,
)

# Module-level assignment: NAME = ["a", "b"] or NAME = {"a": ..., "b": ...}
# We capture the right-hand side
_MODULE_LIST_RE = re.compile(
    r'''^(?P<indent>\s*)(?P<name>[A-Z_][A-Z0-9_]*)\s*=\s*\[(?P<items>[^\]]+)\]''',
    re.MULTILINE | re.DOTALL,
)
_MODULE_DICT_RE = re.compile(
    r'''^(?P<indent>\s*)(?P<name>[A-Z_][A-Z0-9_]*)\s*=\s*\{(?P<items>[^}]+)\}''',
    re.MULTILINE | re.DOTALL,
)

# Individual string items inside a list or dict literal (quoted strings)
_STRING_RE = re.compile(r'''(?P<q>["\'])(?P<val>(?:[^"'\\]|\\.)*)(?P=q)''')


def extract_strings_from_items(items_text: str):
    """Yield (full_match, value) for each quoted string in a list/dict literal."""
    for m in _STRING_RE.finditer(items_text):
        yield m.group(0), m.group("val")


# ─── Per-file processor ───────────────────────────────────────────────────────

def process_file(path: Path, en: dict, dry_run: bool) -> tuple[int, int]:
    """
    Scan *path*, replace hardcoded UI strings with t() calls.
    Returns (strings_replaced, new_keys_added).
    """
    module = path.stem          # e.g. "shortifier"
    # Use parent folder name for disambiguation if needed
    parent = path.parent.name   # e.g. "cutting"

    source = path.read_text(encoding="utf-8")
    original = source

    new_keys: dict[str, str] = {}   # key → English value (only new ones)
    replacements: list[tuple[str, str]] = []  # (old_text, new_text) pairs in source

    def get_or_create_key(text: str) -> str | None:
        """Return locale key for *text*, creating if necessary. None = skip."""
        if should_skip(text):
            return None
        # Check for existing exact match in en_US
        for k, v in en.items():
            if v == text:
                return k
        # Generate new key
        key = make_key(module, text)
        # Avoid collisions
        base = key
        i = 2
        while (key in en and en[key] != text) or (key in new_keys and new_keys[key] != text):
            key = f"{base}_{i}"
            i += 1
        new_keys[key] = text
        return key

    # ── 1. Module-level list constants (CROP_POSITIONS, BG_MODES, etc.) ──────
    def replace_module_list(m: re.Match) -> str:
        name = m.group("name")
        items_text = m.group("items")
        new_items = items_text
        for full, val in extract_strings_from_items(items_text):
            if should_skip(val):
                continue
            key = get_or_create_key(val)
            if key:
                new_items = new_items.replace(full, f't("{key}")', 1)
        if new_items == items_text:
            return m.group(0)
        return m.group(0).replace(items_text, new_items)

    # ── 2. Module-level dict constants (LAYOUTS, AUDIO_SOURCES, etc.) ────────
    # Only translate the KEYS (display labels), not the values
    def replace_module_dict(m: re.Match) -> str:
        name = m.group("name")
        items_text = m.group("items")
        new_items = items_text

        # Find key: value pairs. Keys are the first quoted string before ":"
        # Pattern: "display text": "internal_value"  or  "display": (tuple/str/int)
        pair_re = re.compile(
            r'''(?P<q>["\'])(?P<key>(?:[^"'\\]|\\.)*)(?P=q)\s*:''',
        )
        for pm in pair_re.finditer(items_text):
            key_str = pm.group("key")
            if should_skip(key_str):
                continue
            locale_key = get_or_create_key(key_str)
            if locale_key:
                old = f'{pm.group("q")}{key_str}{pm.group("q")}:'
                new = f't("{locale_key}"):'
                new_items = new_items.replace(old, new, 1)

        if new_items == items_text:
            return m.group(0)
        return m.group(0).replace(items_text, new_items)

    # Apply module-level list replacements
    source = _MODULE_LIST_RE.sub(replace_module_list, source)
    # Apply module-level dict replacements
    source = _MODULE_DICT_RE.sub(replace_module_dict, source)

    # ── 3. values=[...] inside widget calls ──────────────────────────────────
    def replace_values_list(m: re.Match) -> str:
        items_text = m.group("items")
        new_items = items_text
        for full, val in extract_strings_from_items(items_text):
            if should_skip(val):
                continue
            key = get_or_create_key(val)
            if key:
                new_items = new_items.replace(full, f't("{key}")', 1)
        if new_items == items_text:
            return m.group(0)
        return m.group(0).replace(items_text, new_items)

    source = _VALUES_RE.sub(replace_values_list, source)

    # ── 4. text="..." in widget calls ────────────────────────────────────────
    def replace_text_arg(m: re.Match) -> str:
        val = m.group("val")
        if should_skip(val):
            return m.group(0)
        # Skip if it has tkinter variable references or is a concatenation context
        key = get_or_create_key(val)
        if key:
            return f't("{key}")'   # replaces just the value expression
        return m.group(0)

    # We need to replace `text=<expr>` not just the string - rebuild carefully
    def replace_text_kwarg(m: re.Match) -> str:
        val = m.group("val")
        if should_skip(val):
            return m.group(0)
        key = get_or_create_key(val)
        if key:
            return f'text=t("{key}")'
        return m.group(0)

    source = _TEXT_ARG_RE.sub(replace_text_kwarg, source)

    # ── 5. Inline label arrays like clip_labels = ["Left / Top", ...] ────────
    _INLINE_LIST_RE = re.compile(
        r'''(?P<name>\w+)\s*=\s*\[(?P<items>[^\]]+)\]''',
    )
    def replace_inline_list(m: re.Match) -> str:
        name = m.group("name")
        if name.startswith("_") or name.upper() == name:
            return m.group(0)  # already handled above for module-level ALL_CAPS
        items_text = m.group("items")
        new_items = items_text
        changed = False
        for full, val in extract_strings_from_items(items_text):
            if should_skip(val):
                continue
            key = get_or_create_key(val)
            if key:
                new_items = new_items.replace(full, f't("{key}")', 1)
                changed = True
        if not changed:
            return m.group(0)
        return m.group(0).replace(items_text, new_items)

    source = _INLINE_LIST_RE.sub(replace_inline_list, source)

    # ── Merge new keys into en ────────────────────────────────────────────────
    en.update(new_keys)

    changed = source != original
    if changed and not dry_run:
        path.write_text(source, encoding="utf-8")

    return len(new_keys), 1 if changed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing files")
    args = parser.parse_args()

    en = load_en()
    original_key_count = len(en)

    tab_files = list(TABS_DIR.rglob("*.py"))
    tab_files = [f for f in tab_files
                 if "__pycache__" not in str(f)
                 and f.name not in ("__init__.py", "base_tab.py", "registry.py", "all_in_one.py")]

    total_new_keys = 0
    total_changed_files = 0

    print(f"Scanning {len(tab_files)} tab files...")
    print(f"Dry run: {args.dry_run}\n")

    for path in sorted(tab_files):
        new_keys, changed = process_file(path, en, args.dry_run)
        rel = path.relative_to(ROOT)
        if new_keys or changed:
            status = "WOULD CHANGE" if args.dry_run else "CHANGED"
            print(f"  {status}: {rel}  (+{new_keys} new keys)")
        total_new_keys += new_keys
        total_changed_files += changed

    print(f"\nTotal new locale keys: {total_new_keys}")
    print(f"Total files {'that would be' if args.dry_run else ''} changed: {total_changed_files}")
    print(f"en_US keys: {original_key_count} -> {len(en)}")

    if not args.dry_run and total_new_keys > 0:
        save_en(en)
        print("\nen_US.json updated.")
        print("Now run:  python translate_missing.py")


if __name__ == "__main__":
    main()
