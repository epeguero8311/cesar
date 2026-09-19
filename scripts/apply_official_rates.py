#!/usr/bin/env python3
"""
Applies confirmed official first-year acceptance rates to guides-data.json.

For every school in the official-sources file where status == "confirmed"
and a "rate" value is present, overwrites that school's firstYear.rate in
guides-data.json. Schools marked "preliminary" or "none", or "confirmed"
entries with no rate (partial disclosures like admits-only), are left
untouched.

Edits are made as targeted string replacements on the raw file text (not a
full JSON parse+re-dump), so every other byte in guides-data.json --
transfer data, why/overview text, deadlines, formatting/indentation -- is
left exactly as it was. Nothing else changes.

Usage:
    python scripts/apply_official_rates.py <path-to-official-sources.json>
"""
import json
import re
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDES_DATA_PATH = os.path.join(REPO_ROOT, "college-guides", "guides-data.json")


def fmt_rate(rate):
    """30 -> '30%', 4.6 -> '4.6%', 4.0 -> '4%' (confirmed = exact, no '~')."""
    if isinstance(rate, float) and rate.is_integer():
        rate = int(rate)
    return f"{rate}%"


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/apply_official_rates.py <path-to-official-sources.json>")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        sources = json.load(f)

    with open(GUIDES_DATA_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    guides = json.loads(text)  # parsed only to read old values / validate, never re-dumped

    changes = []
    skipped_no_guide_entry = []

    for slug, source in sources.items():
        if slug.startswith("_"):
            continue
        if source.get("status") != "confirmed" or "rate" not in source:
            continue
        if slug not in guides:
            skipped_no_guide_entry.append(slug)
            continue

        old_rate = guides[slug]["firstYear"]["rate"]
        new_rate = fmt_rate(source["rate"])
        if old_rate == new_rate:
            continue

        block_m = re.search(r'"%s"\s*:\s*\{' % re.escape(slug), text)
        if not block_m:
            raise RuntimeError(f"Could not locate block for slug '{slug}' in guides-data.json")

        fy_m = re.search(r'"firstYear"\s*:\s*\{', text[block_m.start():])
        if not fy_m:
            raise RuntimeError(f"Could not locate firstYear for slug '{slug}'")
        fy_start = block_m.start() + fy_m.end()

        rate_m = re.search(r'"rate"\s*:\s*"((?:[^"\\]|\\.)*)"', text[fy_start:])
        if not rate_m:
            raise RuntimeError(f"Could not locate firstYear.rate for slug '{slug}'")

        found_old = json.loads(f'"{rate_m.group(1)}"')
        if found_old != old_rate:
            raise RuntimeError(
                f"Rate mismatch for '{slug}': raw text has {found_old!r}, parsed JSON has {old_rate!r}"
            )

        abs_start = fy_start + rate_m.start()
        abs_end = fy_start + rate_m.end()
        text = text[:abs_start] + f'"rate": "{new_rate}"' + text[abs_end:]

        changes.append((slug, guides[slug]["name"], old_rate, new_rate))

    # Re-parse the fully edited text to confirm it's still valid JSON and that
    # every intended change (and only those) landed correctly.
    updated = json.loads(text)
    for slug, _, _, new_rate in changes:
        assert updated[slug]["firstYear"]["rate"] == new_rate

    with open(GUIDES_DATA_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    print(f"Updated {len(changes)} school(s):\n")
    for slug, name, old, new in changes:
        print(f"  {name} ({slug}): {old} -> {new}")

    if skipped_no_guide_entry:
        print(
            f"\nNote: {len(skipped_no_guide_entry)} slug(s) in official-sources.json "
            f"have no matching entry in guides-data.json: {', '.join(skipped_no_guide_entry)}"
        )


if __name__ == "__main__":
    main()
