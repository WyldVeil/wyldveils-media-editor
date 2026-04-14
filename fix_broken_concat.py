"""
fix_broken_concat.py  --  Fix implicit string concatenations broken by
i18n_audit_fix.py.  Pattern:   t("key")   "remaining tail"
becomes a single t() call with the full combined string as the value.
"""
import re
import json
from pathlib import Path

ROOT       = Path(__file__).parent
TABS_DIR   = ROOT / "tabs"
LOCALE_DIR = ROOT / "locale"

# Pattern:  t("some.key")   <whitespace/newline>   "tail string"
# We need to catch cases like:
#   text=t("key")\n         "tail",
#   text=t("key") "tail",
BROKEN = re.compile(
    r't\("([^"]+)"\)'          # t("key")
    r'(\s*\n?\s*)'             # optional whitespace / newline
    r'"((?:[^"\\]|\\.)*)"'     # "tail string"
)


def load_en():
    with open(LOCALE_DIR / "en_US.json", encoding="utf-8") as f:
        d = json.load(f)
    d.pop("_meta", None)
    return d


def save_en(data):
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


def main():
    en = load_en()
    total_fixed = 0

    for path in sorted(TABS_DIR.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        original = src

        def fix_match(m):
            key      = m.group(1)
            gap      = m.group(2)
            tail     = m.group(3)

            # Reconstruct the full English string
            head_val = en.get(key, key)
            full_val = head_val + tail

            # Re-use the existing key with the full value, or create new key
            # Check if any existing key already has the full string
            for k, v in en.items():
                if v == full_val:
                    return f't("{k}")'

            # Update the existing key to hold the full value
            en[key] = full_val
            return f't("{key}")'

        new_src = BROKEN.sub(fix_match, src)

        if new_src != original:
            path.write_text(new_src, encoding="utf-8")
            fixes = len(BROKEN.findall(original))
            total_fixed += fixes
            print(f"  Fixed {fixes} broken concat(s) in {path.relative_to(ROOT)}")

    save_en(en)
    print(f"\nTotal broken concatenations fixed: {total_fixed}")
    print("en_US.json updated with merged strings.")
    print("Now run: python translate_missing.py")


if __name__ == "__main__":
    main()
