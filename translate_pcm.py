"""
translate_pcm.py  --  Translate missing pcm_NG (Nigerian Pidgin) keys
                      using Meta's NLLB-200 model via Hugging Face Inference API.

Requirements:
    pip install requests

Setup (free):
    1. Create a free account at https://huggingface.co
    2. Go to Settings > Access Tokens > New token (read access is enough)
    3. Run:  set HF_TOKEN=hf_your_token_here
             python translate_pcm.py

The NLLB-200 model was specifically trained on Nigerian Pidgin (pcm_Latn)
by Meta AI as part of their No Language Left Behind initiative.
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

LOCALE_DIR = Path(__file__).parent / "locale"
API_URL = "https://api-inference.huggingface.co/models/facebook/nllb-200-distilled-600M"


def translate_batch(token: str, texts: list[str]) -> list[str]:
    """Translate a list of English strings to Nigerian Pidgin via NLLB-200."""
    headers = {"Authorization": f"Bearer {token}"}
    results = []

    for text in texts:
        payload = {
            "inputs": text,
            "parameters": {
                "src_lang": "eng_Latn",
                "tgt_lang": "pcm_Latn",
                "max_length": 512,
            }
        }
        for attempt in range(3):
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)

            if resp.status_code == 503:
                # Model is loading - HF spins it up on first call
                wait = resp.json().get("estimated_time", 20)
                print(f"\n    Model loading, waiting {wait:.0f}s…", end=" ", flush=True)
                time.sleep(min(float(wait) + 2, 60))
                continue

            if resp.status_code == 429:
                print("\n    Rate limited, waiting 30s…", end=" ", flush=True)
                time.sleep(30)
                continue

            resp.raise_for_status()
            data = resp.json()
            translated = data[0]["translation_text"] if isinstance(data, list) else text
            results.append(translated)
            break
        else:
            results.append(text)   # fallback to English on repeated failure

        time.sleep(0.2)   # gentle pacing

    return results


def main() -> None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print("ERROR: HF_TOKEN environment variable not set.")
        print()
        print("  1. Create a free account at https://huggingface.co")
        print("  2. Go to Settings > Access Tokens > New token (Read)")
        print("  3. Run:  set HF_TOKEN=hf_your_token_here")
        print("           python translate_pcm.py")
        sys.exit(1)

    # Load en_US source
    with open(LOCALE_DIR / "en_US.json", encoding="utf-8") as f:
        en = json.load(f)
    en.pop("_meta", None)

    # Load current pcm_NG
    pcm_path = LOCALE_DIR / "pcm_NG.json"
    with open(pcm_path, encoding="utf-8") as f:
        pcm = json.load(f)
    meta = pcm.pop("_meta", None)

    # Find keys that are still just English copies (added by the en_GB fallback)
    # We need to re-translate all keys that weren't originally in pcm_NG
    # The original pcm_NG only had 191 keys, so anything beyond that is an en_GB copy
    # Safest: just translate everything that matches the en_US value exactly
    # (i.e. was never translated - still has the English string)
    with open(LOCALE_DIR / "en_GB.json", encoding="utf-8") as f:
        en_gb = json.load(f)
    en_gb.pop("_meta", None)

    # Keys to translate: those whose current value equals the en_GB or en_US value
    # (meaning they were filled with English, not actually translated)
    to_translate = {
        k: v for k, v in en.items()
        if pcm.get(k) == en_gb.get(k, v) or pcm.get(k) == v
        # Keep any key where the pcm value differs from both English versions
        # (those were hand-translated by whoever originally built pcm_NG.json)
        if not (k in pcm and pcm[k] != v and pcm[k] != en_gb.get(k))
    }

    # Exclude keys that were genuinely translated in the original pcm_NG
    original_pcm_keys = set()
    # Re-read original to know what was there before the en_GB fill
    # We can infer: any key where pcm value != en_US value AND != en_GB value was original
    for k in list(to_translate.keys()):
        if k in pcm and pcm[k] != en.get(k) and pcm[k] != en_gb.get(k, ""):
            del to_translate[k]  # keep the genuine Pidgin translation

    print(f"Keys to translate into Nigerian Pidgin: {len(to_translate)}")
    print(f"(Keys already genuinely translated: {len(pcm) - len(to_translate)})\n")

    keys   = list(to_translate.keys())
    values = list(to_translate.values())

    translated_count = 0
    total = len(keys)

    for i, (key, eng_text) in enumerate(zip(keys, values)):
        print(f"  [{i+1}/{total}] {key[:50]:<50}  ", end="", flush=True)
        try:
            result = translate_batch(token, [eng_text])
            pcm[key] = result[0]
            translated_count += 1
            # Print a short preview (safe ASCII-ish truncation for Windows console)
            preview = result[0][:40].encode("ascii", errors="replace").decode()
            print(preview)
        except Exception as exc:
            print(f"ERROR: {exc} - keeping English")
            pcm[key] = eng_text

        # Save progress every 50 keys so a crash doesn't lose everything
        if (i + 1) % 50 == 0:
            _save(pcm_path, meta, pcm, en)
            print(f"  --- checkpoint saved ({i+1}/{total}) ---")

    _save(pcm_path, meta, pcm, en)
    print(f"\nDone. Translated {translated_count}/{total} strings into Nigerian Pidgin.")


def _save(path: Path, meta: dict | None, pcm: dict, en_order: dict) -> None:
    output = {}
    if meta:
        output["_meta"] = meta
    for k in en_order:
        if k in pcm:
            output[k] = pcm[k]
    for k, v in pcm.items():
        if k not in output:
            output[k] = v
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
