"""
update_pcm_new_keys.py  --  Fill new keys added to en_US into pcm_NG using
en_GB as the base (same approach as before for unsupported language).
Run this AFTER translate_missing.py finishes.
"""
import json
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locale"

with open(LOCALE_DIR / "en_US.json", encoding="utf-8") as f:
    en = json.load(f)
en.pop("_meta", None)

with open(LOCALE_DIR / "en_GB.json", encoding="utf-8") as f:
    en_gb = json.load(f)
en_gb.pop("_meta", None)

with open(LOCALE_DIR / "pcm_NG.json", encoding="utf-8") as f:
    pcm = json.load(f)
meta = pcm.pop("_meta", None)

filled = 0
for k, v in en.items():
    if k not in pcm:
        pcm[k] = en_gb.get(k, v)
        filled += 1

output = {}
if meta:
    output["_meta"] = meta
for k in en:
    if k in pcm:
        output[k] = pcm[k]

with open(LOCALE_DIR / "pcm_NG.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"pcm_NG.json: filled {filled} new keys. Total: {len(output)}")
