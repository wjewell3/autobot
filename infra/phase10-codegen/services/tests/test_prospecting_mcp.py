"""
Tests for prospecting-mcp service.

Tier 1 — Sacred (from prospecting-agent system message examples)
Tier 2 — Eval-grounded (from eval-harness cases.yaml)
Tier 3 — Domain edge cases
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Import service functions directly
from service import (
    classify_lead,
    check_website_exists,
    normalize_business_name,
    deduplicate_businesses,
    _is_directory,
    _is_outdated,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tier 1: Sacred — from agent system message examples ──────────────────────

def test_classify_lead_hot_only_directories():
    """
    Agent example: Jim's Plumbing — only Yelp/Facebook in search results → HOT.
    """
    results = json.dumps([
        {"url": "https://www.yelp.com/biz/jims-plumbing-chattanooga", "title": "Jim's Plumbing", "content": "4.5 stars"},
        {"url": "https://www.facebook.com/jimsplumbing", "title": "Jim's Plumbing", "content": "Local plumber"},
        {"url": "https://www.yellowpages.com/jims-plumbing", "title": "Jim's Plumbing", "content": ""},
    ])
    result = json.loads(run(classify_lead("Jim's Plumbing", results)))
    assert result["status"] == "HOT"
    assert result["real_website"] is None
    assert len(result["directory_urls"]) >= 2


def test_classify_lead_cold_has_real_website():
    """
    Agent example: business with non-directory URL → COLD (has website, skip it).
    """
    results = json.dumps([
        {"url": "https://www.yelp.com/biz/north-georgia-hvac", "title": "NGHA", "content": ""},
        {"url": "https://ngaheatandair.com", "title": "North Georgia Heating and Air", "content": "Call us today"},
    ])
    result = json.loads(run(classify_lead("North Georgia Heating and Air", results)))
    assert result["status"] == "COLD"
    assert result["real_website"] == "https://ngaheatandair.com"


def test_classify_lead_warm_outdated_site():
    """
    Agent example: site found but copyright 2012 → WARM.
    """
    results = json.dumps([
        {"url": "https://oldplumbingco.com", "title": "Old Plumbing Co", "content": "Copyright 2012. Last updated 2013."},
    ])
    result = json.loads(run(classify_lead("Old Plumbing Co", results)))
    assert result["status"] == "WARM"
    assert "outdated" in result["reason"].lower()


def test_classify_lead_default_cold_when_ambiguous():
    """
    Agent rule: when in doubt, COLD. A Squarespace or generic link = real site.
    """
    results = json.dumps([
        {"url": "https://smithplumbing.squarespace.com", "title": "Smith Plumbing", "content": "Professional plumbing"},
    ])
    result = json.loads(run(classify_lead("Smith Plumbing", results)))
    assert result["status"] == "COLD"


# ── Tier 2: Eval-grounded ─────────────────────────────────────────────────────

def test_classify_lead_empty_results_low_confidence():
    """eval case: empty-niche-handling — no search results → HOT but low confidence."""
    result = json.loads(run(classify_lead("Unknown Co", "[]")))
    assert result["status"] == "HOT"
    assert result["confidence"] in ("medium", "low")


def test_normalize_business_name_basic():
    """
    Eval case: repo-name-format — special chars removed, lowercase, hyphens.
    "Bob's HVAC & Air" → "bobs-hvac-and-air-demo"
    """
    result = json.loads(run(normalize_business_name("Bob's HVAC & Air")))
    assert result["slug"] == "bobs-hvac-and-air-demo"
    assert "'" not in result["slug"]
    assert " " not in result["slug"]


def test_normalize_business_name_with_llc():
    """Common suffix should be included in slug (just normalized)."""
    result = json.loads(run(normalize_business_name("Smith Plumbing, LLC")))
    assert result["slug"] == "smith-plumbing-llc-demo"


def test_normalize_business_name_apostrophe_removed():
    """Apostrophes must be stripped — GitHub repo names can't have them."""
    result = json.loads(run(normalize_business_name("Jim's Roofing")))
    assert "'" not in result["slug"]
    assert result["slug"] == "jims-roofing-demo"


# ── Tier 3: Domain edge cases ─────────────────────────────────────────────────

def test_is_directory_yelp():
    assert _is_directory("https://www.yelp.com/biz/test") is True


def test_is_directory_facebook():
    assert _is_directory("https://www.facebook.com/mybusiness") is True


def test_is_directory_real_site():
    assert _is_directory("https://smithplumbing.com") is False


def test_is_directory_subdomain_of_google():
    assert _is_directory("https://maps.google.com/?q=smith+plumbing") is True


def test_is_outdated_copyright_old():
    assert _is_outdated("© 2012 Smith Plumbing") is True


def test_is_outdated_recent_copyright():
    assert _is_outdated("© 2024 Smith Plumbing") is False


def test_is_outdated_under_construction():
    assert _is_outdated("This site is under construction") is True


def test_deduplicate_removes_llc_variation():
    """
    'Smith Plumbing LLC' and 'Smith Plumbing' should be treated as duplicates.
    """
    businesses = json.dumps([
        {"name": "Smith Plumbing LLC", "address": "123 Main St"},
        {"name": "Smith Plumbing", "address": "123 Main St"},
        {"name": "Jones Electric", "address": "456 Oak Ave"},
    ])
    result = json.loads(run(deduplicate_businesses(businesses)))
    assert result["removed_count"] == 1
    assert result["total"] == 2


def test_deduplicate_empty_list():
    result = json.loads(run(deduplicate_businesses("[]")))
    assert result["businesses"] == []
    assert result["removed_count"] == 0


def test_deduplicate_invalid_json():
    result = json.loads(run(deduplicate_businesses("not json")))
    assert "error" in result


def test_check_website_exists_timeout():
    """Timeout should return structured error, not raise."""
    with patch("service.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.head.side_effect = __import__("httpx").TimeoutException("timed out")
        result = json.loads(run(check_website_exists("https://example.com", timeout=1)))
    assert result["live"] is False
    assert result["error"] == "timeout"


def test_check_website_exists_directory_redirect():
    """If a site redirects to Facebook, mark as is_directory=True."""
    with patch("service.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://www.facebook.com/myshop"
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.head = AsyncMock(return_value=mock_resp)
        result = json.loads(run(check_website_exists("https://myshop.com")))
    assert result["is_directory"] is True


def test_normalize_business_name_unicode():
    """Unicode characters should be stripped gracefully."""
    result = json.loads(run(normalize_business_name("Café Hernández Plumbing")))
    assert result["slug"].endswith("-demo")
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in result["slug"])


def test_classify_lead_malformed_json():
    """Malformed search results should return HOT with low confidence, not crash."""
    result = json.loads(run(classify_lead("Test Co", "this is not json")))
    assert result["status"] == "HOT"  # empty results = HOT
    assert "confidence" in result
