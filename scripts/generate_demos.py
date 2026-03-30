#!/usr/bin/env python3
"""
generate_demos.py — Batch-create demo plumber websites on GitHub Pages.

Reads the CSV output from prospect_plumbers.py, generates a professional
HTML page for each HOT lead, and pushes them to a single GitHub repo
as a multi-page site. Each demo lives at:

    https://<username>.github.io/<repo>/demos/<slug>/

This is way more scalable than creating individual repos per business.
One repo can hold thousands of demos.

Usage:
  # Generate demos for all HOT leads in a city CSV:
  python scripts/generate_demos.py --csv output/prospects/plumbers-nashville-tn.csv

  # Generate from the master hot leads CSV:
  python scripts/generate_demos.py --csv output/prospects/all-hot-leads.csv

  # Limit to first N leads:
  python scripts/generate_demos.py --csv output/prospects/plumbers-nashville-tn.csv --limit 10

  # Dry run (generate HTML locally, don't push to GitHub):
  python scripts/generate_demos.py --csv output/prospects/plumbers-nashville-tn.csv --dry-run

Environment:
  GITHUB_TOKEN   — GitHub personal access token (or uses `gh auth token`)
  GITHUB_USER    — GitHub username (default: wjewell3)
  GITHUB_REPO    — Demo sites repo (default: plumber-demos)

Dependencies:
  pip install httpx  (only dependency)
"""

import argparse
import asyncio
import base64
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

GITHUB_USER = os.environ.get("GITHUB_USER", "wjewell3")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "plumber-demos")
GITHUB_API = "https://api.github.com"
OUTPUT_DIR = Path("output/demos")

# Plumbing-specific template config (from site-builder-mcp.py)
PLUMBING_CONFIG = {
    "primary": "#1A5C8A",
    "secondary": "#0D3A57",
    "emoji": "🔧",
    "services": [
        "Pipe Repair & Replacement",
        "Drain Cleaning & Unclogging",
        "Water Heater Service",
        "Emergency Plumbing",
        "Leak Detection & Repair",
        "Bathroom & Kitchen Plumbing",
    ],
}


# ── GitHub Token ──────────────────────────────────────────────────────────────

def get_github_token() -> str:
    """Get GitHub token from env or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    # Try gh CLI
    try:
        import subprocess
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    print("❌ No GitHub token found. Set GITHUB_TOKEN env var or run `gh auth login`")
    sys.exit(1)


# ── Slug Generator ────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """DNS/GitHub-safe slug from business name."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"\s*[&+]\s*", "-and-", n)
    n = re.sub(r"['\",\.\']", "", n)
    n = re.sub(r"[^a-z0-9]+", "-", n)
    n = re.sub(r"-{2,}", "-", n)
    return n.strip("-")


# ── HTML Template ─────────────────────────────────────────────────────────────

def render_plumber_site(
    business_name: str,
    city: str,
    state: str,
    address: str = "",
    phone: str = "",
) -> str:
    """
    Render a complete plumber website.
    Reuses the proven template from site-builder-mcp.py.
    """
    import html as html_mod

    cfg = PLUMBING_CONFIG
    year = datetime.now().year
    biz = html_mod.escape(business_name)
    city_esc = html_mod.escape(city)
    state_esc = html_mod.escape(state)
    primary = cfg["primary"]
    secondary = cfg["secondary"]
    emoji = cfg["emoji"]

    tagline = f"Your trusted local plumber in {city_esc}, {state_esc}"
    about = (
        f"We provide reliable plumbing services to homeowners and businesses "
        f"throughout {city_esc} and surrounding areas. Our licensed, insured team is "
        f"available for emergency calls and scheduled maintenance alike."
    )

    services_html = ""
    for svc in cfg["services"]:
        services_html += f'      <div class="service-card"><p>{html_mod.escape(svc)}</p></div>\n'

    phone_display = html_mod.escape(phone) if phone else ""
    phone_clean = re.sub(r"[^\d+]", "", phone) if phone else ""
    phone_html = (
        f'      <div class="contact-item">'
        f'<span class="icon">📞</span>'
        f'<span><strong>Phone:</strong> <a href="tel:{phone_clean}">{phone_display}</a></span>'
        f'</div>\n'
    ) if phone else ""

    address_display = html_mod.escape(address) if address else f"Serving {city_esc}, {state_esc}"
    address_encoded = re.sub(r"\s+", "+", address_display)

    cta_href = f"tel:{phone_clean}" if phone_clean else "#contact"
    cta_text = "📞 Call Now" if phone_clean else "📬 Get a Free Quote"

    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Plumber",
        "name": business_name,
        "description": tagline,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": address,
            "addressLocality": city,
            "addressRegion": state,
        },
        "telephone": phone,
        "areaServed": {"@type": "City", "name": city},
    }, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{biz} — {tagline}</title>
  <meta name="description" content="{biz} provides professional plumbing services in {city_esc}, {state_esc}. Licensed, insured, emergency available.">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333; line-height: 1.6; }}
    a {{ color: {primary}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .hero {{ background: {primary}; color: white; padding: 70px 20px 60px; text-align: center; }}
    .hero h1 {{ font-size: 2.6rem; font-weight: 700; margin-bottom: 14px; letter-spacing: -0.5px; }}
    .hero p {{ font-size: 1.15rem; opacity: 0.92; max-width: 560px; margin: 0 auto 24px; }}
    .hero .cta-btn {{ display: inline-block; background: white; color: {primary}; padding: 15px 36px; border-radius: 8px; font-weight: 700; font-size: 1.1rem; transition: opacity .2s; }}
    .hero .cta-btn:hover {{ opacity: .88; text-decoration: none; }}
    .about {{ padding: 50px 20px; background: #fff; text-align: center; }}
    .about p {{ max-width: 680px; margin: 0 auto; font-size: 1.05rem; color: #555; }}
    .services {{ padding: 50px 20px; background: #f5f7fa; }}
    .services h2 {{ text-align: center; font-size: 1.9rem; margin-bottom: 32px; color: {secondary}; }}
    .services-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 18px; max-width: 920px; margin: 0 auto; }}
    .service-card {{ background: white; padding: 22px 18px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.07); text-align: center; font-weight: 600; color: {secondary}; }}
    .contact {{ padding: 50px 20px; background: white; }}
    .contact h2 {{ text-align: center; font-size: 1.9rem; margin-bottom: 32px; color: {secondary}; }}
    .contact-content {{ max-width: 560px; margin: 0 auto; }}
    .contact-item {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 18px; font-size: 1rem; }}
    .contact-item .icon {{ font-size: 1.4rem; flex-shrink: 0; line-height: 1.4; }}
    .cta-section {{ text-align: center; padding: 40px 20px; background: #f5f7fa; }}
    .cta-section .cta-btn {{ display: inline-block; background: {primary}; color: white; padding: 18px 44px; border-radius: 8px; font-weight: 700; font-size: 1.2rem; transition: opacity .2s; }}
    .cta-section .cta-btn:hover {{ opacity: .88; text-decoration: none; }}
    footer {{ background: {secondary}; color: rgba(255,255,255,.75); text-align: center; padding: 22px 20px; font-size: .9rem; }}
    @media (max-width: 600px) {{
      .hero h1 {{ font-size: 1.9rem; }}
      .hero {{ padding: 50px 15px 40px; }}
      .services, .contact, .about {{ padding: 35px 15px; }}
      .services-grid {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }}
    }}
  </style>
</head>
<body>

  <header class="hero">
    <h1>{emoji} {biz}</h1>
    <p>{tagline}</p>
    <a href="{cta_href}" class="cta-btn">{cta_text}</a>
  </header>

  <section class="about" id="about">
    <p>{about}</p>
  </section>

  <section class="services" id="services">
    <h2>Our Services</h2>
    <div class="services-grid">
{services_html}    </div>
  </section>

  <section class="contact" id="contact">
    <h2>Contact Us</h2>
    <div class="contact-content">
      <div class="contact-item">
        <span class="icon">📍</span>
        <span><strong>Address:</strong> {address_display}</span>
      </div>
{phone_html}      <div class="contact-item">
        <span class="icon">🗺️</span>
        <a href="https://maps.google.com/?q={address_encoded}" target="_blank" rel="noopener">Find us on Google Maps</a>
      </div>
    </div>
  </section>

  <section class="cta-section">
    <a href="{cta_href}" class="cta-btn">Get Your Free Estimate Today</a>
  </section>

  <footer>
    <p>&copy; {year} {biz}. All rights reserved. &nbsp;|&nbsp; Serving {city_esc}, {state_esc} and surrounding areas.</p>
  </footer>

  <script type="application/ld+json">
{schema}
  </script>
</body>
</html>"""


# ── GitHub Operations ─────────────────────────────────────────────────────────

async def ensure_repo_exists(client: httpx.AsyncClient, token: str) -> bool:
    """Create the demo repo if it doesn't exist. Enable GitHub Pages."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Check if repo exists
    r = await client.get(f"{GITHUB_API}/repos/{GITHUB_USER}/{GITHUB_REPO}", headers=headers)
    if r.status_code == 200:
        print(f"  📂 Repo {GITHUB_USER}/{GITHUB_REPO} exists")
        return True

    # Create repo
    print(f"  📂 Creating repo {GITHUB_USER}/{GITHUB_REPO}...")
    r = await client.post(
        f"{GITHUB_API}/user/repos",
        headers=headers,
        json={
            "name": GITHUB_REPO,
            "description": "Free demo websites for local plumbing businesses",
            "homepage": f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}",
            "private": False,
            "auto_init": True,
            "has_pages": True,
        },
    )
    if r.status_code not in (201, 422):  # 422 = already exists
        print(f"  ❌ Failed to create repo: {r.status_code} {r.text[:200]}")
        return False

    # Wait for repo to be ready
    await asyncio.sleep(3)

    # Enable GitHub Pages from main branch
    r = await client.post(
        f"{GITHUB_API}/repos/{GITHUB_USER}/{GITHUB_REPO}/pages",
        headers=headers,
        json={"source": {"branch": "main", "path": "/"}},
    )
    if r.status_code in (201, 409):  # 409 = pages already enabled
        print(f"  🌐 GitHub Pages enabled")
    else:
        print(f"  ⚠ Pages setup: {r.status_code} (may need manual enable)")

    return True


async def push_file(
    client: httpx.AsyncClient,
    token: str,
    file_path: str,
    content: str,
    message: str,
) -> bool:
    """Push a single file to the repo via GitHub Contents API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"{GITHUB_API}/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{file_path}"

    # Check if file exists (need sha to update)
    r = await client.get(url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None

    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    r = await client.put(url, headers=headers, json=body)
    if r.status_code in (200, 201):
        return True
    else:
        print(f"    ⚠ Failed to push {file_path}: {r.status_code}")
        return False


# ── Index Page ────────────────────────────────────────────────────────────────

def render_index(demos: list[dict]) -> str:
    """Render a nice index page listing all demo sites."""
    rows = ""
    for d in sorted(demos, key=lambda x: (x["city"], x["name"])):
        slug = d["slug"]
        name = d["name"]
        city = d["city"]
        state = d["state"]
        phone = d.get("phone", "")
        rows += f"""      <tr>
        <td><a href="demos/{slug}/" target="_blank">{name}</a></td>
        <td>{city}, {state}</td>
        <td>{phone}</td>
        <td><a href="demos/{slug}/" target="_blank">View Demo →</a></td>
      </tr>\n"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Plumber Demo Sites — Portfolio</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 20px; color: #333; background: #f5f7fa; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    h1 {{ color: #1A5C8A; margin-bottom: 8px; }}
    .subtitle {{ color: #666; margin-bottom: 24px; }}
    .count {{ background: #1A5C8A; color: white; padding: 2px 10px; border-radius: 12px; font-size: 0.9em; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,.07); }}
    th {{ background: #1A5C8A; color: white; padding: 12px 16px; text-align: left; }}
    td {{ padding: 10px 16px; border-bottom: 1px solid #eee; }}
    tr:hover {{ background: #f0f4f8; }}
    a {{ color: #1A5C8A; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .footer {{ margin-top: 24px; text-align: center; color: #999; font-size: 0.85em; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🔧 Plumber Demo Sites</h1>
    <p class="subtitle">Free demo websites built for local plumbing businesses <span class="count">{len(demos)} sites</span></p>
    <table>
      <thead>
        <tr><th>Business</th><th>Location</th><th>Phone</th><th>Demo</th></tr>
      </thead>
      <tbody>
{rows}      </tbody>
    </table>
    <p class="footer">Generated by Autobot • Each site is a free demo — contact us to put it on your own domain</p>
  </div>
</body>
</html>"""


# ── Main Pipeline ─────────────────────────────────────────────────────────────

async def generate_demos(csv_path: str, limit: int = 0, dry_run: bool = False):
    """Read HOT leads from CSV, generate sites, push to GitHub."""

    # Read CSV
    leads = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") in ("HOT", "WARM"):
                leads.append(row)

    if limit > 0:
        leads = leads[:limit]

    if not leads:
        print("❌ No HOT/WARM leads found in CSV")
        return

    print(f"🏗️  Generating demo sites for {len(leads)} leads from {csv_path}\n")

    # Generate HTML for each lead
    demos: list[dict] = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for lead in leads:
        name = lead.get("name", "").strip()
        city = lead.get("city", "").strip()
        state = lead.get("state", "").strip()
        address = lead.get("address", "").strip()
        phone = lead.get("phone", "").strip()

        if not name:
            continue

        slug = slugify(f"{name}-{city}")
        html_content = render_plumber_site(name, city, state, address, phone)

        # Save locally
        local_dir = OUTPUT_DIR / slug
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "index.html").write_text(html_content, encoding="utf-8")

        demos.append({
            "name": name,
            "city": city,
            "state": state,
            "phone": phone,
            "slug": slug,
            "html": html_content,
        })

        print(f"  ✅ {name} → demos/{slug}/")

    # Generate index
    index_html = render_index(demos)
    (OUTPUT_DIR / "index.html").write_text(index_html, encoding="utf-8")

    print(f"\n📁 Generated {len(demos)} demo sites locally in {OUTPUT_DIR}/")

    if dry_run:
        print("  (dry run — not pushing to GitHub)")
        return

    # Push to GitHub
    token = get_github_token()

    async with httpx.AsyncClient(timeout=30) as client:
        # Ensure repo exists
        if not await ensure_repo_exists(client, token):
            print("❌ Failed to set up GitHub repo")
            return

        # Push index
        print(f"\n📤 Pushing to {GITHUB_USER}/{GITHUB_REPO}...")
        await push_file(client, token, "index.html", index_html, "Update demo site index")

        # Push each demo (rate limit: ~1/second to avoid GitHub API limits)
        for i, demo in enumerate(demos, 1):
            file_path = f"demos/{demo['slug']}/index.html"
            ok = await push_file(
                client, token, file_path, demo["html"],
                f"Add demo: {demo['name']} ({demo['city']}, {demo['state']})"
            )
            status = "✅" if ok else "❌"
            print(f"  [{i}/{len(demos)}] {status} {demo['name']}")
            await asyncio.sleep(1.0)  # GitHub API rate limit

    pages_url = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/"
    print(f"\n{'═'*60}")
    print(f"  🎉 DONE!")
    print(f"  Demos pushed:  {len(demos)}")
    print(f"  Index page:    {pages_url}")
    print(f"  Example demo:  {pages_url}demos/{demos[0]['slug']}/")
    print(f"\n  ⏳ GitHub Pages takes 1-2 minutes to deploy.")
    print(f"     Check status: https://github.com/{GITHUB_USER}/{GITHUB_REPO}/actions")
    print(f"{'═'*60}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate demo plumber websites on GitHub Pages")
    parser.add_argument("--csv", required=True, help="Path to prospects CSV from prospect_plumbers.py")
    parser.add_argument("--limit", type=int, default=0, help="Max demos to generate (0 = all)")
    parser.add_argument("--dry-run", action="store_true", help="Generate HTML locally without pushing to GitHub")

    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"❌ CSV not found: {args.csv}")
        sys.exit(1)

    asyncio.run(generate_demos(args.csv, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
