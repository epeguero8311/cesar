#!/usr/bin/env python3
"""
Weekly source-watch for first-year admissions figures.

HARD CONSTRAINTS (do not weaken these):
  * The ONLY URLs this script ever requests are the "url" values already
    recorded in college-guides/official-sources.json. It never searches the
    web, never guesses a URL, and never follows a link found on a fetched
    page. If a school's "url" is null, it is skipped.
  * This script NEVER writes to college-guides/guides-data.json or
    college-guides/official-sources.json. Its only file output is its own
    state file (scripts/source-watch-state.json), which exists purely to
    remember what a page looked like last time so real changes can be told
    apart from a no-op re-check.
  * Only firstYear-relevant figures are ever in scope. Transfer admissions
    data is permanently out of scope for this system (official-sources.json
    doesn't track transfer figures at all, so this is structural, not just
    a filter).
  * When a change is detected, the only action taken is opening a GitHub
    Issue for a human to review. No page, and no repo file that a human
    maintains by hand, is ever edited automatically.

For status "none" / "preliminary" schools: any content change at the
recorded URL is worth a human look (there's no confirmed rate yet, so any
movement matters). For "confirmed" schools: the same content-change
detection is used (a generic watcher can't reliably out-guess arbitrary
university page layouts), but the issue opened is explicit that the
figures on file should be re-verified against the link, and it surfaces
percentage-like values found on the page as a starting point -- never as
an asserted new figure.

Usage:
    python scripts/source_watch.py [--dry-run]

--dry-run prints what would happen (including issue bodies) without
calling `gh` and without writing the state file. Used for local testing;
the real weekly workflow does not pass this flag.
"""
import argparse
import datetime
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import sys

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(REPO_ROOT, "college-guides", "official-sources.json")
GUIDES_DATA_PATH = os.path.join(REPO_ROOT, "college-guides", "guides-data.json")
STATE_PATH = os.path.join(REPO_ROOT, "scripts", "source-watch-state.json")

USER_AGENT = (
    "FullAxisSourceWatch/1.0 (+https://fullaxiscc.com; "
    "weekly admissions-data change watcher; contact: cesar@fullaxiscc.com)"
)
REQUEST_TIMEOUT = 25
MAX_STORED_CHARS = 20000  # bound on how much normalized text we keep for diffing

TAG_STRIP_PATTERNS = [
    re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S),
    re.compile(r"<style\b[^>]*>.*?</style>", re.I | re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<[^>]+>"),
]
RATE_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,2})?\s?%")

# Best-effort noise stripping for volatile text that isn't inside <script>/<style>
# (those are already removed by TAG_STRIP_PATTERNS): clock timestamps, relative
# "N minutes ago" style text, and "generated/updated at ..." boilerplate. This is
# heuristic, not exhaustive -- a human reviews every flagged issue regardless, so
# an occasional false positive from an unhandled noise pattern is caught there,
# never acted on automatically.
NOISE_TEXT_PATTERNS = [
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm)?\b", re.I),  # clock times
    re.compile(r"\b\d+\s+(?:second|minute|hour|day)s?\s+ago\b", re.I),
    re.compile(
        r"\b(?:generated|last\s+updated|updated|retrieved|fetched|page\s+loaded)\b"
        r"\s*(?:at|on)?\s*[:\-]?\s*[^.;]{0,40}",
        re.I,
    ),
]


def normalize_html(html_text):
    text = html_text
    for pat in TAG_STRIP_PATTERNS:
        text = pat.sub(" ", text)
    text = re.sub(r"&nbsp;", " ", text)
    for pat in NOISE_TEXT_PATTERNS:
        text = pat.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def normalize_pdf(raw_bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    for pat in NOISE_TEXT_PATTERNS:
        text = pat.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def fetch_normalized(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "pdf" in ctype.lower() or url.lower().endswith(".pdf"):
        return normalize_pdf(resp.content)
    return normalize_html(resp.text)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_rate_candidates(text, limit=15):
    seen = []
    for m in RATE_PATTERN.findall(text):
        if m not in seen:
            seen.append(m)
        if len(seen) >= limit:
            break
    return seen


def diff_snippet(old_text, new_text, context=80):
    sm = difflib.SequenceMatcher(None, old_text, new_text)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            old_snip = old_text[max(0, i1 - context):i2 + context].strip()
            new_snip = new_text[max(0, j1 - context):j2 + context].strip()
            return old_snip, new_snip
    return "", ""


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def ensure_label(name, color, description):
    gh("label", "create", name, "--color", color, "--description", description, "--force")


def issue_already_open(slug):
    result = gh(
        "issue", "list", "--state", "open",
        "--label", f"source-watch:{slug}", "--json", "number",
    )
    if result.returncode != 0:
        print(f"  warning: gh issue list failed for {slug}: {result.stderr.strip()}", file=sys.stderr)
        return False
    try:
        return len(json.loads(result.stdout)) > 0
    except json.JSONDecodeError:
        return False


def build_issue_body(slug, status, url, on_file, page_candidates, old_snip, new_snip):
    lines = [
        "The recorded source page changed since the last weekly check.",
        "",
        f"- **Status on file:** `{status}`",
        f"- **Source URL:** {url}",
        "",
        "### Figures currently on file (`college-guides/official-sources.json`)",
        "```json",
        json.dumps(on_file, indent=2),
        "```",
    ]
    if status == "confirmed":
        lines += [
            "",
            "### Percentage-like values found on the page just now",
            "_Best-effort text scan of the page — not an asserted new figure, just a starting "
            "point. Verify the real number at the link above before changing anything._",
            "- " + ", ".join(page_candidates) if page_candidates else "_none found_",
        ]
    lines += [
        "",
        "### What changed (excerpt)",
        "_Limited to a window around the first detected difference in the page's normalized "
        f"text, within the first {MAX_STORED_CHARS:,} characters. For long pages the real "
        "change may be outside this excerpt — always check the link._",
        "",
        "**Before:**",
        "```",
        f"...{old_snip}..." if old_snip else "(no prior excerpt on file)",
        "```",
        "**After:**",
        "```",
        f"...{new_snip}..." if new_snip else "(no difference found in excerpt window)",
        "```",
        "",
        "---",
        "Opened automatically by the weekly source-watch workflow "
        "(`.github/workflows/source-watch.yml` / `scripts/source_watch.py`). This system only "
        "reads the URL already recorded above — it never searches the web or guesses a URL, "
        "and it never edits `guides-data.json` or `official-sources.json` itself. A human must "
        "verify the figure at the source and update those files manually.",
    ]
    return "\n".join(lines)


def open_issue(slug, name, status, url, on_file, page_candidates, old_snip, new_snip, dry_run):
    title = f"[Source Watch] {name} — recorded source page changed"
    body = build_issue_body(slug, status, url, on_file, page_candidates, old_snip, new_snip)

    if dry_run:
        print(f"\n--- DRY RUN: would open issue for {slug} ---")
        print(f"Title: {title}")
        print(body)
        print("--- end ---\n")
        return

    ensure_label("source-watch", "0e8a16", "Automated weekly admissions-source change watch")
    ensure_label(f"source-watch:{slug}", "fbca04", f"Source-watch flag for {slug}")

    result = gh(
        "issue", "create",
        "--title", title,
        "--body", body,
        "--label", "source-watch",
        "--label", f"source-watch:{slug}",
    )
    if result.returncode != 0:
        print(f"  ERROR: failed to create issue for {slug}: {result.stderr.strip()}", file=sys.stderr)
    else:
        print(f"  opened issue for {slug}: {result.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = load_json(SOURCES_PATH, {})
    guides = load_json(GUIDES_DATA_PATH, {})
    state = load_json(STATE_PATH, {})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    any_state_change = False

    for slug, entry in sources.items():
        if slug.startswith("_"):
            continue
        status = entry.get("status")
        if status not in ("none", "preliminary", "confirmed"):
            continue

        url = entry.get("url")
        if not url:
            print(f"{slug}: no URL on file, skipping")
            continue

        print(f"{slug}: checking {url}")
        try:
            full_text = fetch_normalized(url)
        except Exception as e:  # network/parse errors: skip, don't flag as a change
            print(f"  fetch failed: {e}", file=sys.stderr)
            continue

        new_hash = sha256(full_text)
        excerpt = full_text[:MAX_STORED_CHARS]
        prev = state.get(slug)

        if prev is None:
            state[slug] = {"hash": new_hash, "excerpt": excerpt, "url": url, "last_checked": now}
            any_state_change = True
            print("  no prior baseline; recorded one now")
            continue

        if prev.get("url") != url:
            # The maintainer changed the recorded URL itself -- re-baseline rather
            # than flag a false "content changed" against a different page.
            state[slug] = {"hash": new_hash, "excerpt": excerpt, "url": url, "last_checked": now}
            any_state_change = True
            print("  URL on file changed since last run; re-baselined without flagging")
            continue

        if prev.get("hash") == new_hash:
            prev["last_checked"] = now
            any_state_change = True
            print("  no change")
            continue

        print("  CHANGE DETECTED")
        old_snip, new_snip = diff_snippet(prev.get("excerpt", ""), excerpt)
        page_candidates = extract_rate_candidates(full_text)
        name = guides.get(slug, {}).get("name", slug)
        on_file = {k: v for k, v in entry.items() if k != "url"}

        if not args.dry_run and issue_already_open(slug):
            print("  an open source-watch issue already exists for this school; not duplicating")
        else:
            open_issue(slug, name, status, url, on_file, page_candidates, old_snip, new_snip, args.dry_run)

        state[slug] = {"hash": new_hash, "excerpt": excerpt, "url": url, "last_checked": now}
        any_state_change = True

    if args.dry_run:
        print("\nDRY RUN: not writing state file")
    elif any_state_change:
        save_json(STATE_PATH, state)
        print(f"\nState file updated: {STATE_PATH}")
    else:
        print("\nNo state changes to write")


if __name__ == "__main__":
    main()
