"""
translate_missing.py  --  Fill missing locale keys using Google Translate (free).

Usage:
    python translate_missing.py                 # all languages
    python translate_missing.py --lang de_DE    # one language
    python translate_missing.py --dry-run       # preview only

Requires:  pip install deep-translator
"""

import json
import re
import sys
import time
import argparse
from pathlib import Path

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("ERROR: deep-translator not installed. Run: pip install deep-translator")
    sys.exit(1)

# ---------------------------------------------------------------------------
LOCALE_DIR = Path(__file__).parent / "locale"

# Maps our locale codes → Google Translate target language codes
GOOGLE_LANG = {
    "en_GB":  "en",
    "zh_CN":  "zh-CN",
    "hi_IN":  "hi",
    "es_ES":  "es",
    "ar_MSA": "ar",
    "fr_FR":  "fr",
    "bn_BD":  "bn",
    "pt_BR":  "pt",
    "id_ID":  "id",
    "ur_PK":  "ur",
    "ru_RU":  "ru",
    "de_DE":  "de",
    "ja_JP":  "ja",
    "pcm_NG": None,   # Nigerian Pidgin not supported by Google Translate - skip
    "vi_VN":  "vi",
    "ko_KR":  "ko",
    "it_IT":  "it",
    "tr_TR":  "tr",
    "pl_PL":  "pl",
    "nl_NL":  "nl",
    "th_TH":  "th",
    "fa_IR":  "fa",
    "sw_KE":  "sw",
    "tl_PH":  "tl",
    "uk_UA":  "uk",
    "ro_RO":  "ro",
    "ms_MY":  "ms",
}

# Tokens we don't want Google to mangle - wrap in a placeholder, restore after
# Pattern: {varname}, file extensions, common technical terms
_PROTECT_RE = re.compile(
    r'(\{[^}]+\})'          # {placeholder} variables
)

def _protect(text: str) -> tuple[str, list[str]]:
    """Replace protected tokens with §0§, §1§, … and return the map."""
    tokens: list[str] = []
    def replacer(m: re.Match) -> str:
        tokens.append(m.group(0))
        return f"§{len(tokens)-1}§"
    return _PROTECT_RE.sub(replacer, text), tokens

def _restore(text: str, tokens: list[str]) -> str:
    for i, tok in enumerate(tokens):
        text = text.replace(f"§{i}§", tok)
    return text


def translate_batch(target_lang: str, keys: list[str], values: list[str]) -> dict[str, str]:
    """
    Translate a list of UI strings into target_lang.
    Joins them with a delimiter so it's a single API call per batch.
    """
    SEP = " ⟦§⟧ "   # unlikely to appear in normal text

    protected: list[str] = []
    token_maps: list[list[str]] = []
    for v in values:
        p, toks = _protect(v)
        protected.append(p)
        token_maps.append(toks)

    joined = SEP.join(protected)

    translator = GoogleTranslator(source="en", target=target_lang)
    translated_joined = translator.translate(joined)

    # Google sometimes translates the separator; normalise common variants
    # Try splitting on the original separator first, then fallback variations
    if translated_joined is None:
        translated_joined = joined  # no change

    parts = translated_joined.split(SEP)

    # If the split count doesn't match, try a looser split
    if len(parts) != len(values):
        # Google may have altered the separator slightly
        parts = re.split(r'\s*[⟦\[]\s*§\s*[⟧\]]\s*', translated_joined)

    # Pad or trim to match expected count
    while len(parts) < len(values):
        parts.append(values[len(parts)])  # fallback to English
    parts = parts[:len(values)]

    result: dict[str, str] = {}
    for i, key in enumerate(keys):
        restored = _restore(parts[i].strip(), token_maps[i])
        result[key] = restored or values[i]

    return result


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  saved {path.name}")


def process_language(lang_code: str, google_code: str, en_strings: dict,
                     batch_size: int, dry_run: bool) -> None:
    lang_file = LOCALE_DIR / f"{lang_code}.json"
    if not lang_file.exists():
        print(f"  SKIP {lang_code}: file not found")
        return

    existing = load_json(lang_file)
    meta = existing.pop("_meta", None)

    missing_keys = [k for k in en_strings if k not in existing]
    if not missing_keys:
        print(f"  {lang_code}: already complete ({len(existing)} keys)")
        return

    print(f"  {lang_code}: {len(missing_keys)} keys to translate…")

    if dry_run:
        print(f"    [dry-run] {len(missing_keys)} keys in batches of {batch_size}")
        return

    translated_count = 0
    total_batches = (len(missing_keys) + batch_size - 1) // batch_size

    for batch_num, batch_start in enumerate(range(0, len(missing_keys), batch_size), 1):
        batch_keys   = missing_keys[batch_start: batch_start + batch_size]
        batch_values = [en_strings[k] for k in batch_keys]
        print(f"    batch {batch_num}/{total_batches} ({len(batch_keys)} strings)…", end=" ", flush=True)

        try:
            translations = translate_batch(google_code, batch_keys, batch_values)
            existing.update(translations)
            translated_count += len(translations)
            print(f"done  ({translated_count}/{len(missing_keys)})")
        except Exception as exc:
            print(f"FAILED: {exc}")
            print(f"    Retrying in 5s…")
            time.sleep(5)
            try:
                translations = translate_batch(google_code, batch_keys, batch_values)
                existing.update(translations)
                translated_count += len(translations)
                print(f"    retry ok  ({translated_count}/{len(missing_keys)})")
            except Exception as exc2:
                print(f"    Retry also failed ({exc2}), skipping batch.")

        time.sleep(0.3)   # be polite to Google's free endpoint

    # Rebuild file: _meta first, then keys in en_US order
    output: dict = {}
    if meta is not None:
        output["_meta"] = meta
    for k in en_strings:
        if k in existing:
            output[k] = existing[k]
    for k, v in existing.items():
        if k not in output:
            output[k] = v

    save_json(lang_file, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Translate missing locale keys via Google Translate")
    parser.add_argument("--lang", help="Only process this language (e.g. de_DE)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--batch-size", type=int, default=40,
                        help="Strings per API call (default 40; lower = safer)")
    args = parser.parse_args()

    en_data = load_json(LOCALE_DIR / "en_US.json")
    en_data.pop("_meta", None)

    if args.lang:
        if args.lang not in GOOGLE_LANG:
            print(f"Unknown language code: {args.lang}")
            sys.exit(1)
        languages = [args.lang]
    else:
        languages = [code for code in GOOGLE_LANG]

    print(f"Source: {len(en_data)} English strings")
    print(f"Languages: {len(languages)}  |  Batch size: {args.batch_size}  |  Dry run: {args.dry_run}\n")

    skipped = []
    for lang in languages:
        gcode = GOOGLE_LANG.get(lang)
        if gcode is None:
            print(f"  {lang}: no Google Translate code - skipping")
            skipped.append(lang)
            continue
        process_language(lang, gcode, en_data, args.batch_size, args.dry_run)

    if skipped:
        print(f"\nSkipped (unsupported by Google Translate): {', '.join(skipped)}")
    print("\nDone.")


if __name__ == "__main__":
    main()
