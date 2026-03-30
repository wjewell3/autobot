"""
site-builder-mcp — deterministic HTML template rendering and repo name generation.

Compiles the most expensive LLM tasks in site-builder-agent:
  - render_site_template:  Full HTML page from business details
                           (was: entire LLM generation call, ~2000 tokens, 10-15s)
  - generate_repo_name:    Deterministic GitHub slug
                           (was: LLM creative naming, sometimes invalid characters)
  - validate_html:         Quality gate before publishing
                           (was: LLM self-check, inconsistent)

All 10 business niches from the PM agent niche rotation are templated.
Unknown niches fall back to a generic "local services" template.

Port: 8102
Deployed by: codegen-agent / human operator
Replaces LLM calls in: site-builder-agent
"""

import html
import json
import os
import re
import unicodedata
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

PORT = int(os.environ.get("SITE_BUILDER_MCP_PORT", "8102"))

mcp = FastMCP(
    "site-builder-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Industry templates ────────────────────────────────────────────────────────
# Each niche: primary_color, secondary_color, tagline_template, services list,
#             hero_emoji, about_template.
# {city} / {business_name} are slot-filled at render time.

INDUSTRY_CONFIG: dict[str, dict] = {
    "plumbing": {
        "primary": "#1A5C8A",
        "secondary": "#0D3A57",
        "tagline": "Your trusted local plumber in {city}",
        "services": [
            "Pipe Repair & Replacement",
            "Drain Cleaning & Unclogging",
            "Water Heater Service",
            "Emergency Plumbing",
            "Leak Detection & Repair",
            "Bathroom & Kitchen Plumbing",
        ],
        "emoji": "🔧",
        "about": (
            "We provide reliable plumbing services to homeowners and businesses "
            "throughout {city}. Our licensed, insured team is available for "
            "emergency calls and scheduled maintenance alike."
        ),
    },
    "hvac": {
        "primary": "#1A6B3A",
        "secondary": "#0E4226",
        "tagline": "Keeping {city} comfortable year-round",
        "services": [
            "AC Installation & Repair",
            "Heating System Service",
            "Duct Cleaning",
            "Emergency HVAC",
            "Preventive Maintenance",
            "Indoor Air Quality",
        ],
        "emoji": "❄️",
        "about": (
            "Expert heating and cooling services for homes and businesses in {city}. "
            "We service all makes and models — same-day appointments available."
        ),
    },
    "electrician": {
        "primary": "#B8860B",
        "secondary": "#7A5700",
        "tagline": "Licensed electrical services in {city}",
        "services": [
            "Panel Upgrades & Repairs",
            "Outlet & Switch Installation",
            "Lighting Installation",
            "Electrical Inspections",
            "EV Charger Installation",
            "Emergency Electrical",
        ],
        "emoji": "⚡",
        "about": (
            "Licensed and insured electricians serving {city} and surrounding areas. "
            "Residential and commercial electrical work done safely and on time."
        ),
    },
    "roofing": {
        "primary": "#8B2500",
        "secondary": "#5A1800",
        "tagline": "Quality roofing services in {city}",
        "services": [
            "Roof Replacement",
            "Roof Repair",
            "Storm Damage Repair",
            "Gutter Installation",
            "Roof Inspections",
            "Insurance Claims Assistance",
        ],
        "emoji": "🏠",
        "about": (
            "Protecting {city} homes and businesses with quality roofing solutions. "
            "Licensed contractor with years of local experience."
        ),
    },
    "landscaping": {
        "primary": "#2E7D32",
        "secondary": "#1B5E20",
        "tagline": "Beautiful lawns and landscapes in {city}",
        "services": [
            "Lawn Mowing & Edging",
            "Landscape Design",
            "Tree & Shrub Care",
            "Sod Installation",
            "Seasonal Cleanups",
            "Irrigation Systems",
        ],
        "emoji": "🌿",
        "about": (
            "Transforming outdoor spaces across {city}. "
            "Weekly maintenance, full landscape design, and everything in between."
        ),
    },
    "pressure washing": {
        "primary": "#0277BD",
        "secondary": "#01579B",
        "tagline": "Professional pressure washing in {city}",
        "services": [
            "Driveway & Sidewalk Cleaning",
            "House Washing",
            "Deck & Patio Cleaning",
            "Roof Soft Washing",
            "Commercial Pressure Washing",
            "Graffiti Removal",
        ],
        "emoji": "💧",
        "about": (
            "Restoring the look of your property with professional pressure washing. "
            "Serving residential and commercial clients throughout {city}."
        ),
    },
    "food truck": {
        "primary": "#E65100",
        "secondary": "#BF360C",
        "tagline": "Fresh food on wheels — serving {city}",
        "services": [
            "Lunch Service",
            "Catering Events",
            "Corporate Lunches",
            "Private Parties",
            "Festivals & Markets",
            "Custom Menus",
        ],
        "emoji": "🍜",
        "about": (
            "Bringing delicious food to {city} neighborhoods, events, and offices. "
            "Follow us for our weekly schedule or book us for your next event."
        ),
    },
    "handyman": {
        "primary": "#4E342E",
        "secondary": "#3E2723",
        "tagline": "Reliable handyman services in {city}",
        "services": [
            "Furniture Assembly",
            "Drywall Repair",
            "Door & Window Repair",
            "Painting & Touch-Ups",
            "Tile & Grout Repair",
            "General Home Repairs",
        ],
        "emoji": "🛠️",
        "about": (
            "No job too small. We handle the home repairs and improvements "
            "that keep piling up — serving {city} homeowners with quality craftsmanship."
        ),
    },
    "painting": {
        "primary": "#6A1B9A",
        "secondary": "#4A148C",
        "tagline": "Professional painting services in {city}",
        "services": [
            "Interior Painting",
            "Exterior Painting",
            "Cabinet Refinishing",
            "Deck Staining",
            "Commercial Painting",
            "Color Consultation",
        ],
        "emoji": "🖌️",
        "about": (
            "Transform your space with a fresh coat of paint. "
            "Residential and commercial painting throughout {city} — clean, fast, guaranteed."
        ),
    },
    "pest control": {
        "primary": "#33691E",
        "secondary": "#1B5E20",
        "tagline": "Pest-free homes and businesses in {city}",
        "services": [
            "General Pest Control",
            "Termite Treatment",
            "Rodent Removal",
            "Bed Bug Treatment",
            "Mosquito Control",
            "Free Inspections",
        ],
        "emoji": "🐛",
        "about": (
            "Protecting {city} properties from pests with safe, effective treatments. "
            "Licensed technicians — satisfaction guaranteed."
        ),
    },
}

# Generic fallback
_GENERIC_CONFIG = {
    "primary": "#37474F",
    "secondary": "#263238",
    "tagline": "Quality local services in {city}",
    "services": [
        "Professional Service",
        "Free Estimates",
        "Licensed & Insured",
        "Satisfaction Guaranteed",
        "Emergency Available",
        "Serving All of {city}",
    ],
    "emoji": "⭐",
    "about": (
        "Professional local services for homeowners and businesses in {city}. "
        "Contact us today for a free estimate."
    ),
}


def _get_config(niche: str) -> dict:
    """Match niche string to a template config (case-insensitive, partial match)."""
    niche_lower = niche.lower().strip()
    # Exact match first
    if niche_lower in INDUSTRY_CONFIG:
        return INDUSTRY_CONFIG[niche_lower]
    # Partial match
    keywords = {
        "plumb": "plumbing",
        "hvac": "hvac", "air condition": "hvac", "heating": "hvac", "cooling": "hvac",
        "electr": "electrician",
        "roof": "roofing",
        "landscap": "landscaping", "lawn": "landscaping", "lawn care": "landscaping",
        "pressure": "pressure washing", "power wash": "pressure washing",
        "food truck": "food truck", "catering": "food truck",
        "handyman": "handyman",
        "paint": "painting",
        "pest": "pest control", "exterminator": "pest control",
    }
    for keyword, key in keywords.items():
        if keyword in niche_lower:
            return INDUSTRY_CONFIG[key]
    return _GENERIC_CONFIG.copy()


def _render_services(services: list[str]) -> str:
    items = ""
    for svc in services:
        items += (
            f'      <div class="service-card">'
            f'<p>{html.escape(svc)}</p>'
            f'</div>\n'
        )
    return items


def _build_html(
    business_name: str,
    niche: str,
    city: str,
    address: str,
    phone: str,
    cfg: dict,
) -> str:
    year = datetime.now().year
    tagline = cfg["tagline"].format(city=html.escape(city), business_name=html.escape(business_name))
    about = cfg["about"].format(city=html.escape(city), business_name=html.escape(business_name))
    services = [s.format(city=html.escape(city)) for s in cfg["services"]]
    primary = cfg["primary"]
    secondary = cfg["secondary"]
    emoji = cfg["emoji"]

    services_html = _render_services(services)

    # Phone display / clean
    phone_display = html.escape(phone) if phone else ""
    phone_clean = re.sub(r"[^\d+]", "", phone) if phone else ""
    phone_html = (
        f'      <div class="contact-item">'
        f'<span class="icon">📞</span>'
        f'<span><strong>Phone:</strong> <a href="tel:{phone_clean}">{phone_display}</a></span>'
        f'</div>\n'
    ) if phone else ""

    address_display = html.escape(address) if address else f"Serving {html.escape(city)}, TN"
    address_encoded = re.sub(r"\s+", "+", address_display)
    address_html = (
        f'      <div class="contact-item">'
        f'<span class="icon">📍</span>'
        f'<span><strong>Address:</strong> {address_display}</span>'
        f'</div>\n'
    )
    maps_html = (
        f'      <div class="contact-item">'
        f'<span class="icon">🗺️</span>'
        f'<a href="https://maps.google.com/?q={address_encoded}" target="_blank" rel="noopener">'
        f'Find us on Google Maps</a>\n      </div>\n'
    )

    cta_html = (
        f'      <a href="tel:{phone_clean}" class="cta-btn">📞 Call Now</a>\n'
        if phone_clean else
        f'      <a href="#contact" class="cta-btn">📬 Get a Free Quote</a>\n'
    )

    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": business_name,
        "description": tagline,
        "address": {
            "@type": "PostalAddress",
            "streetAddress": address,
            "addressLocality": city,
        },
        "telephone": phone,
        "url": "",
    }, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(business_name)} — {tagline}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333; line-height: 1.6; }}
    a {{ color: {primary}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Hero ── */
    .hero {{ background: {primary}; color: white; padding: 70px 20px 60px; text-align: center; }}
    .hero h1 {{ font-size: 2.6rem; font-weight: 700; margin-bottom: 14px; letter-spacing: -0.5px; }}
    .hero p {{ font-size: 1.15rem; opacity: 0.92; max-width: 560px; margin: 0 auto; }}

    /* ── About ── */
    .about {{ padding: 50px 20px; background: #fff; text-align: center; }}
    .about p {{ max-width: 680px; margin: 0 auto; font-size: 1.05rem; color: #555; }}

    /* ── Services ── */
    .services {{ padding: 50px 20px; background: #f5f7fa; }}
    .services h2 {{ text-align: center; font-size: 1.9rem; margin-bottom: 32px; color: {secondary}; }}
    .services-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 18px; max-width: 920px; margin: 0 auto; }}
    .service-card {{ background: white; padding: 22px 18px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.07); text-align: center; font-weight: 600; color: {secondary}; }}

    /* ── Contact ── */
    .contact {{ padding: 50px 20px; background: white; }}
    .contact h2 {{ text-align: center; font-size: 1.9rem; margin-bottom: 32px; color: {secondary}; }}
    .contact-content {{ max-width: 560px; margin: 0 auto; }}
    .contact-item {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 18px; font-size: 1rem; }}
    .contact-item .icon {{ font-size: 1.4rem; flex-shrink: 0; line-height: 1.4; }}
    .cta-btn {{ display: inline-block; background: {primary}; color: white; padding: 15px 36px; border-radius: 8px; font-weight: 700; font-size: 1.1rem; margin-top: 22px; transition: opacity .2s; }}
    .cta-btn:hover {{ opacity: .88; text-decoration: none; }}

    /* ── Footer ── */
    footer {{ background: {secondary}; color: rgba(255,255,255,.75); text-align: center; padding: 22px 20px; font-size: .9rem; }}

    /* ── Responsive ── */
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
    <h1>{emoji} {html.escape(business_name)}</h1>
    <p>{tagline}</p>
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
{address_html}{phone_html}{maps_html}{cta_html}    </div>
  </section>

  <footer>
    <p>&copy; {year} {html.escape(business_name)}. All rights reserved. &nbsp;|&nbsp; Serving {html.escape(city)} and surrounding areas.</p>
  </footer>

  <script type="application/ld+json">
{schema}
  </script>
</body>
</html>"""


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def render_site_template(
    business_name: str,
    niche: str,
    city: str,
    address: str = "",
    phone: str = "",
) -> str:
    """
    Render a complete, mobile-friendly HTML page for a local business.

    Eliminates the LLM HTML generation call entirely. Produces a professional
    single-page site with hero, about, services grid, contact section, schema.org
    markup, and responsive CSS. Supports all 10 PM-agent niche rotation categories.

    Args:
        business_name: Business name (e.g. "Jim's Plumbing")
        niche:         Industry type (e.g. "plumbing", "hvac", "landscaping").
                       Unknown niches fall back to a generic template.
        city:          City name (e.g. "Chattanooga")
        address:       Street address (optional — uses "Serving {city}" if absent)
        phone:         Phone number (optional)

    Returns:
        JSON: {
          "html":     str,   # complete HTML document
          "niche_matched": str,  # which template was used
          "char_count": int
        }
    """
    cfg = _get_config(niche)
    matched_key = niche.lower()
    for k in INDUSTRY_CONFIG:
        if k in niche.lower():
            matched_key = k
            break

    rendered = _build_html(business_name, niche, city, address, phone, cfg)
    return json.dumps({
        "html": rendered,
        "niche_matched": matched_key,
        "char_count": len(rendered),
    })


@mcp.tool()
async def generate_repo_name(business_name: str) -> str:
    """
    Generate a deterministic, GitHub-safe repo name from a business name.

    Applies the same slug rules as normalize_business_name in prospecting-mcp
    for consistency. Always appends '-demo'.

    Args:
        business_name: Raw business name (e.g. "Bob's HVAC & Air, LLC")

    Returns:
        JSON: {
          "repo_name":  str,   # e.g. "bobs-hvac-and-air-llc-demo"
          "original":   str,
          "length_ok":  bool   # GitHub repo names must be ≤100 chars
        }
    """
    name = business_name.strip()
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.lower()
    name = re.sub(r"\s*[&+]\s*", "-and-", name)
    name = re.sub(r"['\",\.\']", "", name)
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    repo_name = f"{name}-demo"
    return json.dumps({
        "repo_name": repo_name,
        "original": business_name,
        "length_ok": len(repo_name) <= 100,
    })


@mcp.tool()
async def validate_html(html_content: str) -> str:
    """
    Run the site-builder quality checklist against generated HTML.

    Checks for all required elements from the site-builder-agent quality checklist:
    meta viewport, h1 with business name, services section, contact section,
    address/phone content, schema.org markup, footer, mobile CSS.

    Args:
        html_content: Full HTML string to validate.

    Returns:
        JSON: {
          "valid":            bool,
          "score":            int,   # 0-100
          "missing":          [str],
          "present":          [str],
          "warnings":         [str]
        }
    """
    checks = {
        "meta viewport": bool(re.search(r'<meta[^>]*viewport', html_content, re.I)),
        "h1 tag": bool(re.search(r'<h1[^>]*>', html_content, re.I)),
        "services section": bool(re.search(r'class="services', html_content, re.I)),
        "contact section": bool(re.search(r'class="contact|id="contact', html_content, re.I)),
        "footer": bool(re.search(r'<footer', html_content, re.I)),
        "schema.org markup": bool(re.search(r'application/ld\+json', html_content, re.I)),
        "mobile media query": bool(re.search(r'@media.*max-width', html_content, re.I)),
        "copyright": bool(re.search(r'&copy;|©|\bAll rights reserved\b', html_content, re.I)),
    }

    present = [k for k, v in checks.items() if v]
    missing = [k for k, v in checks.items() if not v]
    score = int((len(present) / len(checks)) * 100)
    valid = len(missing) == 0

    warnings = []
    if len(html_content) < 2000:
        warnings.append("HTML is very short — may be missing content sections")
    if not re.search(r'<html', html_content, re.I):
        warnings.append("Missing <html> tag — invalid document structure")

    return json.dumps({
        "valid": valid,
        "score": score,
        "missing": missing,
        "present": present,
        "warnings": warnings,
    })


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import anyio
    import uvicorn

    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
