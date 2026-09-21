#!/usr/bin/env python3
"""
Generates static college-guides/<slug>.html pages from college-guides/guides-data.json,
and rewrites sitemap.xml so the guide URLs point at the static pages instead of
guide.html?school=<slug>.

Run whenever guides-data.json changes:
    python scripts/generate_guides.py
"""
import html
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDES_DIR = os.path.join(REPO_ROOT, "college-guides")
DATA_PATH = os.path.join(GUIDES_DIR, "guides-data.json")
SITEMAP_PATH = os.path.join(REPO_ROOT, "sitemap.xml")
SITE_URL = "https://fullaxiscc.com"
LOGO_URL = f"{SITE_URL}/IMG_4736-removebg-preview.png"

# Mirrors the SHORT_NAME_OVERRIDES map in guide.html's client-side script.
SHORT_NAME_OVERRIDES = {
    "Massachusetts Institute of Technology": "MIT",
    "University of Pennsylvania": "Penn",
    "California Institute of Technology": "Caltech",
    "University of Chicago": "UChicago",
    "UC Berkeley": "UC Berkeley",
    "Johns Hopkins University": "Johns Hopkins",
    "Washington University in St. Louis": "WashU",
    "University of Southern California": "USC",
    "Carnegie Mellon University": "Carnegie Mellon",
    "University of Notre Dame": "Notre Dame",
    "University of Michigan": "Michigan",
    "University of California, Los Angeles": "UCLA",
    "New York University": "NYU",
    "University of Virginia": "UVA",
    "University of Texas at Austin": "UT Austin",
    "University of North Carolina at Chapel Hill": "UNC Chapel Hill",
    "Georgia Institute of Technology": "Georgia Tech",
    "University of California, San Diego": "UC San Diego",
    "University of Illinois Urbana-Champaign": "UIUC",
    "Harvey Mudd College": "Harvey Mudd",
    "Claremont McKenna College": "Claremont McKenna",
    "Wake Forest University": "Wake Forest",
    "Washington and Lee University": "Washington and Lee",
    "William & Mary": "William & Mary",
    "University of Florida": "Florida",
    "University of Washington": "UW",
    "University of Miami": "Miami",
    "Boston University": "BU",
    "Boston College": "Boston College",
}


def short_name(full_name):
    return SHORT_NAME_OVERRIDES.get(full_name, full_name.split(" ")[0])


def esc_attr(s):
    """Escape for use inside a double-quoted HTML attribute."""
    return html.escape(s, quote=True)


def esc_text(s):
    """Escape for use as HTML text content (data has no raw < or >, only bare &)."""
    return s.replace("&", "&amp;")


def paragraphs(items):
    return "".join(f"<p>{esc_text(p)}</p>" for p in items)


def list_items(items):
    return "".join(f"<li>{esc_text(li)}</li>" for li in items)


def build_section(label, s, school_name):
    return f"""
      <div class="guide-stat-bar reveal">
        <div class="guide-stat-tile"><div class="label">{label} Acceptance Rate</div><div class="value">{esc_text(s['rate'])}</div></div>
        <div class="guide-stat-tile"><div class="label">Application Deadline</div><div class="value">{esc_text(s['deadline'])}</div></div>
        <div class="guide-stat-tile"><div class="label">Decisions Released</div><div class="value">{esc_text(s['decisionsReleased'])}</div></div>
        <div class="guide-stat-tile"><div class="label">Terms Offered</div><div class="value">{esc_text(s['terms'])}</div></div>
      </div>

      <h2>Overview</h2>
      {paragraphs(s['overview'])}

      <h2>What {esc_text(short_name(school_name))} Looks For</h2>
      <ul>{list_items(s['lookingFor'])}</ul>

      <h2>Requirements &amp; Deadlines</h2>
      <ul>{list_items(s['requirements'])}</ul>

      <div class="mentor-tie-in">
        <p><strong>Disclaimer:</strong> {esc_text(s['mentor']['text'])}</p>
      </div>

      <p class="data-note">{esc_text(s['dataNote'])}</p>
    """


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<link rel="icon" type="image/png" href="../Untitled_design__1_-removebg-preview.png" />
<title>{title}</title>
<meta name="description" content="{description}" />
<link rel="canonical" href="{canonical}" />

<meta property="og:type" content="website" />
<meta property="og:title" content="{title}" />
<meta property="og:description" content="{description}" />
<meta property="og:url" content="{canonical}" />
<meta property="og:image" content="{logo}" />
<meta property="og:site_name" content="Full Axis College Consulting" />

<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Poppins:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet" />
<link rel="stylesheet" href="../style.css" />
</head>
<body>

<!-- NAV -->
<nav>
  <div class="nav-brand">
    <a href="../index.html"><img src="../IMG_4736-removebg-preview.png" alt="Full Axis" class="nav-logo-img" /></a>
  </div>
  <button class="nav-burger" id="navBurger" aria-label="Toggle menu" aria-expanded="false">
    <span></span><span></span><span></span>
  </button>

  <ul class="nav-links" id="navLinks">
    <li><a href="../index.html#mission">About</a></li>
    <li><a href="../index.html#team">Team</a></li>
    <li><a href="../index.html#pricing">Packages</a></li>
    <li><a href="../mission/index.html">Mission</a></li>
    <li><a href="../college-guides/index.html">College Guides</a></li>
    <li><a href="../axis-board/index.html">Axis Board</a></li>
    <li><a href="../fellowship.html">FGLI</a></li>
    <li><a href="../index.html#apply" class="nav-cta">Apply Now</a></li>
  </ul>
</nav>
<div class="nav-overlay" id="navOverlay"></div>

<!-- SUB HERO -->
<section class="sub-hero">
  <div class="sub-hero-inner">
    <div class="hero-eyebrow">{eyebrow}</div>
    <h1 class="sub-hero-title">{name} <em>Admissions Guide</em></h1>
    <div class="hero-rule"></div>
    <p class="sub-hero-sub">Decision dates, requirements, and what the admissions committee actually prioritizes — for both first-year and transfer applicants.</p>
  </div>
</section>

<section class="guide-detail">
  <div class="section-inner">
    <div class="guide-body">
      {why_section}
      <div class="section-label guide-section-heading">First-Year Admissions</div>
      {first_year_section}

      <hr class="guide-section-divider" />

      <div class="section-label guide-section-heading">Transfer Admissions</div>
      {transfer_section}
    </div>
  </div>
</section>

<!-- CTA -->
<section id="apply">
  <div class="section-inner">
    <div class="apply-grid reveal">
      <div>
        <div class="section-label"></div>
        <h2 class="apply-title">Targeting <em>{short_name}?</em></h2>
        <p class="apply-sub">Work directly with a mentor who's been through the process. Submit your application and a member of our team will reach out within 48 hours.</p>
        <div class="consult-callout">
          <strong>✦ Free First Consultation (Included With Every Application)</strong>
          <p>Every student who applies receives a complimentary initial consultation at no cost. We assess your profile and identify the best pathway forward — no commitment required.</p>
        </div>
      </div>
      <div class="apply-box">
        <div class="apply-icon">
          <svg viewBox="0 0 24 24"><path d="M9 12l2 2 4-4M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        </div>
        <h3>Apply Now</h3>
        <p>Complete our short intake form. Every application is reviewed personally by our team.</p>
        <a href="https://docs.google.com/forms/d/e/1FAIpQLSdoFQlOemhVGL9cHiw1zWZMkfWvCgZNxgydIc3T4HkZGuN4dA/viewform?usp=header"
        target="_blank" rel="noopener noreferrer" class="btn-apply">Begin Your Application →</a>
        <p class="apply-fine">Beta Cycle — 2026–2027 Admissions Year</p>
      </div>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="ft-logo"> <span></span></div>
  <div class="ft-note">Full Axis is currently operating in its beta cycle for the 2026–2027 admissions year. Prestige-focused, major-specific admissions advisory.</div>
  <div class="ft-right">
    <div class="ft-social">
      <a href="https://www.instagram.com/fullaxisconsulting?igsh=MTVjaGZybGl2OHJxNw==" target="_blank" rel="noopener noreferrer" aria-label="Instagram">
        <svg viewBox="0 0 24 24" stroke="white" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
          <circle cx="12" cy="12" r="4"/>
          <circle cx="17.5" cy="6.5" r="0.5" fill="white" stroke="none"/>
        </svg>
      </a>
      <a href="https://www.tiktok.com/@fullaxiscc?_r=1&_t=ZP-95ywb3mjwBK" target="_blank" rel="noopener noreferrer" aria-label="TikTok">
        <svg viewBox="0 0 24 24" fill="white" stroke="none">
          <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1V9.01a6.33 6.33 0 00-.79-.05 6.34 6.34 0 00-6.34 6.34 6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.33-6.34V8.69a8.24 8.24 0 004.84 1.56V6.81a4.85 4.85 0 01-1.07-.12z"/>
        </svg>
      </a>
      <a href="https://www.linkedin.com/company/full-axis-cc" target="_blank" rel="noopener noreferrer" aria-label="LinkedIn">
        <svg viewBox="0 0 24 24" stroke="white" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
          <line x1="7" y1="10" x2="7" y2="17"/>
          <circle cx="7" cy="6.5" r="0.5" fill="white" stroke="none"/>
          <path d="M11 17v-5c0-1.4 1.1-2.5 2.5-2.5s2.5 1.1 2.5 2.5v5"/>
        </svg>
      </a>
      <a href="https://www.youtube.com/@fullaxiscc" target="_blank" rel="noopener noreferrer" aria-label="YouTube">
        <svg viewBox="0 0 24 24" stroke="white" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="5" width="20" height="14" rx="4" ry="4"/>
          <path d="M10 9l6 3-6 3z"/>
        </svg>
      </a>
    </div>
    <div class="ft-copy">© 2026 Full Axis</div>
  </div>
</footer>
<style>
.ft-right{{display:flex;flex-direction:column;align-items:flex-end;gap:0.75rem}}
@media(max-width:580px){{.ft-right{{align-items:center}}}}
.guide-section-heading{{margin-top:3rem}}
.guide-section-heading:first-child{{margin-top:0}}
.guide-section-divider{{border:none;border-top:1px solid rgba(255,255,255,0.12);margin:3rem 0}}
</style>

<script src="../main.js"></script>
</body>
</html>
"""


def build_page(school):
    name = school["name"]
    short = short_name(name)
    title = f"{name} First-Year & Transfer Acceptance Rate | Full Axis"
    description = school["blurb"]
    canonical = f"{SITE_URL}/college-guides/{school['slug']}.html"

    why = school.get("why") or []
    why_section = ""
    if why:
        why_section = (
            f'<div class="section-label guide-section-heading">Why Consider {esc_text(short)}</div>\n'
            f"      {paragraphs(why)}\n"
            f'      <hr class="guide-section-divider" />'
        )

    return PAGE_TEMPLATE.format(
        title=esc_attr(title),
        description=esc_attr(description),
        canonical=canonical,
        logo=LOGO_URL,
        eyebrow=esc_text(school["eyebrow"]),
        name=esc_text(name),
        why_section=why_section,
        first_year_section=build_section("First-Year", school["firstYear"], name),
        transfer_section=build_section("Transfer", school["transfer"], name),
        short_name=esc_text(short),
    )


def update_sitemap(slugs):
    if not os.path.exists(SITEMAP_PATH):
        print(f"Skipping sitemap update — {SITEMAP_PATH} not found")
        return

    with open(SITEMAP_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Drop old guide.html?school= entries, and any previously-generated static
    # guide entries too, so reruns are idempotent.
    kept = [
        line for line in lines
        if "college-guides/guide.html?school=" not in line
        and not any(f"/college-guides/{slug}.html<" in line for slug in slugs)
    ]

    closing_idx = next(i for i, line in enumerate(kept) if "</urlset>" in line)

    guide_lines = [
        f"  <url><loc>{SITE_URL}/college-guides/{slug}.html</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>\n"
        for slug in slugs
    ]

    new_lines = kept[:closing_idx] + guide_lines + kept[closing_idx:]

    with open(SITEMAP_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(new_lines)

    print(f"Updated {SITEMAP_PATH} with {len(guide_lines)} static guide URLs")


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    slugs = []
    for key, school in data.items():
        slug = school["slug"]
        slugs.append(slug)
        out_path = os.path.join(GUIDES_DIR, f"{slug}.html")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(build_page(school))

    print(f"Generated {len(slugs)} static guide pages in {GUIDES_DIR}")
    update_sitemap(slugs)


if __name__ == "__main__":
    main()
