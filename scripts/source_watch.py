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
  * Sources that can't be fetched are reported, never worked around: once a
    source has failed FAILURE_WEEKS_BEFORE_REPORT runs in a row it is listed
    in ONE open GitHub Issue ("sources that couldn't be checked") that is
    updated each run and closed once nothing qualifies. One-off blocks (a
    site refusing a single run) are not reported, because they usually
    clear up by the next run.
    The fetch identifies itself honestly and makes no attempt to defeat
    anti-bot challenges. A site that refuses just lands on that list.

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
import time

import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES_PATH = os.path.join(REPO_ROOT, "college-guides", "official-sources.json")
GUIDES_DATA_PATH = os.path.join(REPO_ROOT, "college-guides", "guides-data.json")
STATE_PATH = os.path.join(REPO_ROOT, "scripts", "source-watch-state.json")

# Keep this request plain. A dry run showed that a browser-style User-Agent and
# Accept header made things worse (Cornell started returning 403 and Rice 406)
# without unblocking any site that was already refusing us.
USER_AGENT = (
    "FullAxisSourceWatch/1.0 (+https://fullaxiscc.com; "
    "weekly admissions-data change watcher; contact: cesar@fullaxiscc.com)"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT}
REQUEST_TIMEOUT = 25
REQUEST_PAUSE_SECONDS = 1  # be polite: one request per second across ~60 sites
FAILURES_LABEL = "source-watch-failures"
FAILURES_TITLE = "[Source Watch] Sources that couldn't be checked"
FAILURE_WEEKS_BEFORE_REPORT = 2  # consecutive failed runs before a source is listed
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
    # One retry, only for failures that can be transient (5xx, connection, timeout).
    # A 403/404 is a definite answer from the site, so it is not retried.
    for attempt in (1, 2):
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            break
        except requests.HTTPError as e:
            if attempt == 1 and e.response is not None and e.response.status_code >= 500:
                time.sleep(3)
                continue
            raise
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 1:
                time.sleep(3)
                continue
            raise
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


def classify_failure(exc):
    """Return (category, plain-English explanation) for a failed fetch."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        if code in (401, 403, 405, 429):
            return "blocked", (
                f"HTTP {code}: the site refused an automated request. Open the link in a "
                "browser; if it loads, the page is fine but can't be watched automatically."
            )
        if code in (404, 410):
            return "dead_link", (
                f"HTTP {code}: page not found. The URL in official-sources.json is "
                "probably wrong or has moved."
            )
        if code >= 500:
            return "server_error", f"HTTP {code}: the school's server errored (may clear up on its own)."
        return "other", f"HTTP {code}"
    msg = str(exc)
    if isinstance(exc, requests.ConnectionError):
        if "NameResolutionError" in msg or "getaddrinfo" in msg or "Name or service not known" in msg:
            return "dns", "The hostname doesn't resolve. The domain in official-sources.json is probably wrong."
        return "connection", "Couldn't connect to the site."
    if isinstance(exc, requests.Timeout):
        return "timeout", "The site didn't respond in time."
    return "other", msg[:150]


FAILURE_HEADINGS = [
    ("dead_link", "Dead links (need a corrected URL)"),
    ("dns", "Hostname doesn't resolve (need a corrected URL)"),
    ("blocked", "Site refuses automated requests"),
    ("server_error", "Server errors (often temporary)"),
    ("timeout", "Timeouts (often temporary)"),
    ("connection", "Connection problems"),
    ("other", "Other"),
]


def build_failures_body(failures, no_url, total_with_url, pending=0):
    lines = [
        f"Of **{total_with_url}** sources with a URL on file, **{len(failures)}** have failed to load "
        f"for {FAILURE_WEEKS_BEFORE_REPORT}+ weeks in a row. **These schools are not being watched** "
        "until the problem is fixed.",
        "",
    ]
    if pending:
        lines += [
            f"_{pending} more source{'s' if pending != 1 else ''} failed this week for the first time "
            "and will be listed here if they fail again next week._",
            "",
        ]
    for category, heading in FAILURE_HEADINGS:
        rows = [f for f in failures if f["category"] == category]
        if not rows:
            continue
        lines += [f"### {heading} ({len(rows)})", "", "| School | Status on file | Weeks failing | Problem | Link |", "|---|---|---|---|---|"]
        for f in rows:
            lines.append(f"| {f['name']} (`{f['slug']}`) | `{f['status']}` | {f['weeks']} | {f['reason']} | {f['url']} |")
        lines.append("")
    if no_url:
        names = ", ".join(f"{n} (`{s}`)" for s, n in no_url)
        lines += [
            f"### No URL recorded ({len(no_url)})",
            "",
            f"Nothing to watch yet for: {names}.",
            "",
        ]
    lines += [
        "---",
        "Maintained automatically by the weekly source-watch workflow: updated every run and "
        "closed once every source loads. It never edits `official-sources.json`, so fixing a link "
        "is a manual edit, and the watcher only ever checks URLs already listed there.",
    ]
    return "\n".join(lines)


def find_open_failures_issue():
    result = gh("issue", "list", "--state", "open", "--label", FAILURES_LABEL, "--json", "number")
    if result.returncode != 0:
        print(f"  warning: gh issue list failed for failures issue: {result.stderr.strip()}", file=sys.stderr)
        return None
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return items[0]["number"] if items else None


def sync_failures_issue(failures, no_url, total_with_url, pending, dry_run):
    body = build_failures_body(failures, no_url, total_with_url, pending) if failures else None

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and body:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## {FAILURES_TITLE}\n\n{body}\n")

    if dry_run:
        if body:
            print(f"\n--- DRY RUN: would create/update issue '{FAILURES_TITLE}' ---")
            print(body)
            print("--- end ---\n")
        else:
            print(f"\nDRY RUN: no source has failed {FAILURE_WEEKS_BEFORE_REPORT}+ weeks in a row "
                  f"({pending} failed once); would close any open failures issue")
        return

    existing = find_open_failures_issue()
    if failures:
        ensure_label(FAILURES_LABEL, "d93f0b", "Sources the weekly watcher couldn't fetch")
        if existing:
            result = gh("issue", "edit", str(existing), "--body", body)
            print(f"  updated failures issue #{existing}" if result.returncode == 0
                  else f"  ERROR updating failures issue: {result.stderr.strip()}")
        else:
            result = gh("issue", "create", "--title", FAILURES_TITLE, "--body", body, "--label", FAILURES_LABEL)
            print(f"  opened failures issue: {result.stdout.strip()}" if result.returncode == 0
                  else f"  ERROR creating failures issue: {result.stderr.strip()}")
    elif existing:
        gh("issue", "comment", str(existing), "--body",
           f"No source has failed {FAILURE_WEEKS_BEFORE_REPORT}+ weeks in a row, so closing.")
        gh("issue", "close", str(existing))
        print(f"  nothing qualifies this week; closed failures issue #{existing}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = load_json(SOURCES_PATH, {})
    guides = load_json(GUIDES_DATA_PATH, {})
    state = load_json(STATE_PATH, {})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    any_state_change = False
    failures = []   # sources we tried to read but couldn't (this run)
    prior_fail_counts = state.get("_failures", {})  # consecutive failed runs per slug, from last run
    fail_counts = {}
    no_url = []     # sources with nothing recorded to watch
    total_with_url = 0

    for slug, entry in sources.items():
        if slug.startswith("_"):
            continue
        status = entry.get("status")
        if status not in ("none", "preliminary", "confirmed"):
            continue

        url = entry.get("url")
        name = guides.get(slug, {}).get("name", slug)
        if not url:
            print(f"{slug}: no URL on file, skipping")
            no_url.append((slug, name))
            continue

        total_with_url += 1
        print(f"{slug}: checking {url}")
        time.sleep(REQUEST_PAUSE_SECONDS)
        try:
            full_text = fetch_normalized(url)
        except Exception as e:  # network/parse errors: report it, don't flag as a change
            print(f"  fetch failed: {e}", file=sys.stderr)
            category, reason = classify_failure(e)
            weeks = prior_fail_counts.get(slug, 0) + 1
            fail_counts[slug] = weeks
            failures.append({"slug": slug, "name": name, "status": status, "url": url,
                             "category": category, "reason": reason, "weeks": weeks})
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
        on_file = {k: v for k, v in entry.items() if k != "url"}

        if not args.dry_run and issue_already_open(slug):
            print("  an open source-watch issue already exists for this school; not duplicating")
        else:
            open_issue(slug, name, status, url, on_file, page_candidates, old_snip, new_snip, args.dry_run)

        state[slug] = {"hash": new_hash, "excerpt": excerpt, "url": url, "last_checked": now}
        any_state_change = True

    reportable = [f for f in failures if f["weeks"] >= FAILURE_WEEKS_BEFORE_REPORT]
    if fail_counts != prior_fail_counts:
        state["_failures"] = fail_counts
        any_state_change = True
    sync_failures_issue(reportable, no_url, total_with_url, len(failures) - len(reportable), args.dry_run)

    if args.dry_run:
        print("\nDRY RUN: not writing state file")
    elif any_state_change:
        save_json(STATE_PATH, state)
        print(f"\nState file updated: {STATE_PATH}")
    else:
        print("\nNo state changes to write")


if __name__ == "__main__":
    main()
