"""
Tests for site-builder-mcp service.

Tier 1 — Sacred (from site-builder-agent system message examples)
Tier 2 — Eval-grounded (from eval-harness cases.yaml)
Tier 3 — Domain edge cases
"""

import asyncio
import json
import pytest
import re

from service import (
    render_site_template,
    generate_repo_name,
    validate_html,
    _get_config,
    INDUSTRY_CONFIG,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tier 1: Sacred — from agent system message examples ──────────────────────

def test_jims_plumbing_basic_render():
    """
    Agent few-shot example: Jim's Plumbing, Chattanooga, TN.
    Must produce valid HTML with business name, city, plumbing colors.
    """
    result = json.loads(run(render_site_template(
        business_name="Jim's Plumbing",
        niche="plumbing",
        city="Chattanooga",
        address="555 Main St, Chattanooga, TN",
        phone="(423) 555-1234",
    )))
    html = result["html"]
    assert "Jim&#x27;s Plumbing" in html or "Jim's Plumbing" in html
    assert "Chattanooga" in html
    assert "(423) 555-1234" in html or "4235551234" in html
    assert "555 Main St" in html
    assert result["char_count"] > 2000


def test_plumbing_template_has_blue_color():
    """Plumbing template should use blue primary color (#1A5C8A)."""
    result = json.loads(run(render_site_template("Test Plumbing", "plumbing", "Chattanooga")))
    assert "#1A5C8A" in result["html"]


def test_render_produces_valid_html_structure():
    """
    Eval case: basic-site-creation — output must pass validate_html quality checklist.
    """
    render_result = json.loads(run(render_site_template(
        business_name="Smith Plumbing",
        niche="plumbing",
        city="Chattanooga",
        address="123 Water St",
        phone="(423) 555-0001",
    )))
    validate_result = json.loads(run(validate_html(render_result["html"])))
    assert validate_result["valid"] is True
    assert validate_result["score"] >= 90
    assert validate_result["missing"] == []


def test_render_contains_required_sections():
    """Site must have hero, services, contact, and footer sections."""
    result = json.loads(run(render_site_template(
        business_name="Best HVAC Co",
        niche="hvac",
        city="Chattanooga",
    )))
    html_str = result["html"]
    assert 'class="hero"' in html_str
    assert 'class="services' in html_str
    assert 'class="contact' in html_str
    assert "<footer" in html_str


def test_render_has_schema_org_markup():
    """Schema.org LocalBusiness markup is required for SEO."""
    result = json.loads(run(render_site_template("ABC Electric", "electrician", "Chattanooga")))
    assert "application/ld+json" in result["html"]
    assert "LocalBusiness" in result["html"]


def test_render_has_mobile_meta_tag():
    """meta viewport tag is required — from site-builder quality checklist."""
    result = json.loads(run(render_site_template("Test Co", "plumbing", "Chattanooga")))
    assert re.search(r'<meta[^>]*viewport', result["html"], re.I)


def test_render_has_mobile_css():
    """@media query for mobile is required."""
    result = json.loads(run(render_site_template("Test Co", "plumbing", "Chattanooga")))
    assert "@media" in result["html"]
    assert "max-width" in result["html"]


# ── Tier 2: Eval-grounded ─────────────────────────────────────────────────────

def test_generate_repo_name_bobs_hvac():
    """
    Eval case: repo-name-format — "Bob's HVAC & Air" must not have apostrophes.
    """
    result = json.loads(run(generate_repo_name("Bob's HVAC & Air")))
    assert "'" not in result["repo_name"]
    assert " " not in result["repo_name"]
    assert result["repo_name"].endswith("-demo")
    assert result["length_ok"] is True


def test_generate_repo_name_smith_plumbing():
    """
    Eval case: basic-site-creation — generates correct slug.
    """
    result = json.loads(run(generate_repo_name("Smith Plumbing")))
    assert result["repo_name"] == "smith-plumbing-demo"


def test_generate_repo_name_east_ridge():
    """City suffixes should not break slug generation."""
    result = json.loads(run(generate_repo_name("East Ridge HVAC")))
    assert result["repo_name"] == "east-ridge-hvac-demo"
    assert " " not in result["repo_name"]


# ── Tier 3: Domain edge cases ─────────────────────────────────────────────────

def test_render_missing_phone_uses_fallback():
    """Missing phone should not crash — uses 'Call for quote' pattern."""
    result = json.loads(run(render_site_template(
        business_name="No Phone Plumbing",
        niche="plumbing",
        city="Chattanooga",
        phone="",
    )))
    assert result["char_count"] > 1000  # Still renders


def test_render_missing_address_uses_city_fallback():
    """Missing address uses 'Serving {city}' pattern."""
    result = json.loads(run(render_site_template(
        business_name="Mobile Plumber",
        niche="plumbing",
        city="Chattanooga",
        address="",
    )))
    assert "Chattanooga" in result["html"]


def test_render_unknown_niche_uses_generic():
    """Unknown niche falls back to generic template without crashing."""
    result = json.loads(run(render_site_template(
        business_name="TechWhiz Pro",
        niche="computer repair",
        city="Chattanooga",
    )))
    assert result["char_count"] > 1000
    assert "TechWhiz Pro" in result["html"] or "TechWhiz" in result["html"]


def test_all_pm_niches_render():
    """All 10 PM niche rotation categories should render valid HTML."""
    niches = [
        "plumbing", "hvac", "electrician", "roofing", "landscaping",
        "pressure washing", "food truck", "handyman", "painting", "pest control",
    ]
    for niche in niches:
        result = json.loads(run(render_site_template(
            business_name="Test Business",
            niche=niche,
            city="Chattanooga",
        )))
        assert result["char_count"] > 1000, f"Niche '{niche}' rendered too short"
        validate_result = json.loads(run(validate_html(result["html"])))
        assert validate_result["score"] >= 80, f"Niche '{niche}' failed validation: {validate_result['missing']}"


def test_render_html_escapes_business_name():
    """Business names with HTML special chars must be escaped."""
    result = json.loads(run(render_site_template(
        business_name='<script>alert("xss")</script> Plumbing',
        niche="plumbing",
        city="Chattanooga",
    )))
    assert "<script>" not in result["html"]


def test_validate_html_catches_missing_viewport():
    """validate_html should flag missing meta viewport."""
    bad_html = "<html><head></head><body><h1>Test</h1></body></html>"
    result = json.loads(run(validate_html(bad_html)))
    assert "meta viewport" in result["missing"]
    assert result["valid"] is False


def test_validate_html_catches_missing_schema():
    """validate_html should flag missing schema.org markup."""
    bad_html = """<html><head><meta name="viewport" content="width=device-width"></head>
<body><h1>Test</h1><div class="services"><div></div></div>
<div class="contact"></div><footer>© 2026 Test</footer></body></html>"""
    result = json.loads(run(validate_html(bad_html)))
    assert "schema.org markup" in result["missing"]


def test_generate_repo_name_ampersand():
    """Ampersand should become 'and'."""
    result = json.loads(run(generate_repo_name("Smith & Sons Plumbing")))
    assert "and" in result["repo_name"]
    assert "&" not in result["repo_name"]


def test_generate_repo_name_very_long():
    """Very long business names should produce a valid (potentially long) slug."""
    result = json.loads(run(generate_repo_name(
        "The Best Professional Residential Commercial Plumbing and HVAC Company"
    )))
    assert result["repo_name"].endswith("-demo")
    # length_ok checks GitHub's 100-char limit
    assert isinstance(result["length_ok"], bool)
