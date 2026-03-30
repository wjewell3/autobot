"""
Tests for outreach-mcp service.

Tier 1 — Sacred (from outreach-agent system message examples)
Tier 2 — Eval-grounded (from eval-harness cases.yaml)
Tier 3 — Domain edge cases + phase enforcement verification
"""

import asyncio
import json
import os
import pytest

from service import render_email, validate_email_draft, _count_words

OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "jewell.will@gmail.com")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tier 1: Sacred — from agent system message examples ──────────────────────

def test_render_email_testing_phase_goes_to_operator():
    """
    CRITICAL — TESTING phase MUST send to operator, never to prospect.
    This is a hard safety rule in the agent system message.
    """
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        phase="TESTING",
        prospect_email="prospect@example.com",
    )))
    assert result["recipient"] == OPERATOR_EMAIL
    assert result["recipient"] != "prospect@example.com"
    assert result["test_mode"] is True


def test_render_email_subject_has_test_prefix_in_testing():
    """TESTING phase subject must be prefixed with [TEST]."""
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        phase="TESTING",
    )))
    assert result["subject"].startswith("[TEST]")


def test_render_email_production_goes_to_prospect():
    """PRODUCTION phase must use the real prospect email."""
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        phase="PRODUCTION",
        prospect_email="owner@smithplumbing.com",
    )))
    assert result["recipient"] == "owner@smithplumbing.com"
    assert result["test_mode"] is False
    assert not result["subject"].startswith("[TEST]")


def test_render_email_demo_url_in_body():
    """
    Eval case: email-draft-quality — demo URL must appear in body.
    """
    demo = "https://wjewell3.github.io/smith-plumbing-demo"
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url=demo,
        phase="TESTING",
    )))
    assert demo in result["body_html"]


def test_render_email_business_name_in_body_or_subject():
    """
    Eval case: email-draft-quality — business name must appear.
    """
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        phase="TESTING",
    )))
    assert "Smith Plumbing" in result["subject"] or "Smith Plumbing" in result["body_html"]


def test_render_email_no_dear_sir_madam():
    """
    Eval case: email-draft-quality — must not use "Dear Sir/Madam" or "To whom it may concern".
    """
    result = json.loads(run(render_email(
        business_name="Test Business",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://example.com/demo",
        phase="TESTING",
    )))
    body_lower = result["body_html"].lower()
    assert "dear sir" not in body_lower
    assert "to whom it may concern" not in body_lower


def test_render_email_under_150_words():
    """Email body should be under 150 words (excluding test banner)."""
    result = json.loads(run(render_email(
        business_name="Smith Plumbing",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        phase="TESTING",
    )))
    assert result["word_count"] <= 150


# ── Tier 2: Eval-grounded ─────────────────────────────────────────────────────

def test_validate_email_catches_missing_url():
    """validate_email_draft should flag when demo URL is absent from body."""
    result = json.loads(run(validate_email_draft(
        subject="Free demo for Smith Plumbing",
        body_html="<p>Hi there, I noticed you don't have a website.</p>",
        demo_url="https://example.com/smith-demo",
        business_name="Smith Plumbing",
    )))
    assert result["valid"] is False
    assert "demo_url_in_body" in result["issues"]


def test_validate_email_passes_good_draft():
    """A well-formed email should pass validation."""
    result = json.loads(run(validate_email_draft(
        subject="Free demo website for Smith Plumbing",
        body_html=(
            "<p>Hi there,</p><p>I noticed Smith Plumbing in Chattanooga doesn't have a website.</p>"
            "<p>View your demo: <a href='https://wjewell3.github.io/smith-plumbing-demo'>"
            "https://wjewell3.github.io/smith-plumbing-demo</a></p>"
            "<p>Take a look and let me know what you think!</p><p>Will</p>"
        ),
        demo_url="https://wjewell3.github.io/smith-plumbing-demo",
        business_name="Smith Plumbing",
    )))
    assert result["valid"] is True
    assert result["issues"] == []


def test_hitl_gate_not_bypassed():
    """
    Eval case: hitl-gate — render_email NEVER sends email itself.
    It only renders. The agent still has to call gmail_send_email separately.
    Verify the tool returns rendered content, not a send confirmation.
    """
    result = json.loads(run(render_email(
        business_name="Test Business",
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://example.com/demo",
        phase="TESTING",
    )))
    # Should return rendering data, not "sent" status
    assert "sent" not in str(result).lower()
    assert "body_html" in result
    assert "recipient" in result


# ── Tier 3: Phase enforcement edge cases ──────────────────────────────────────

def test_testing_phase_case_insensitive():
    """'testing', 'TESTING', 'Testing' all trigger test mode."""
    for phase in ["testing", "TESTING", "Testing"]:
        result = json.loads(run(render_email(
            business_name="Test Co", business_type="plumbing",
            city="Chattanooga", demo_url="https://x.com/d",
            phase=phase, prospect_email="real@prospect.com",
        )))
        assert result["recipient"] == OPERATOR_EMAIL, f"Failed for phase={phase}"
        assert result["test_mode"] is True


def test_production_phase_with_no_prospect_email_falls_back_to_operator():
    """PRODUCTION with no prospect email should fall back to operator (safe default)."""
    result = json.loads(run(render_email(
        business_name="Test Co", business_type="plumbing",
        city="Chattanooga", demo_url="https://x.com/d",
        phase="PRODUCTION", prospect_email="",
    )))
    assert result["recipient"] == OPERATOR_EMAIL


def test_test_banner_present_in_testing():
    """Test banner must appear in TESTING mode body."""
    result = json.loads(run(render_email(
        business_name="Test Co", business_type="plumbing",
        city="Chattanooga", demo_url="https://x.com/d",
        phase="TESTING", prospect_email="prospect@real.com",
    )))
    assert "TEST MODE" in result["body_html"]
    assert "prospect@real.com" in result["body_html"]


def test_test_banner_absent_in_production():
    """Test banner must NOT appear in PRODUCTION mode."""
    result = json.loads(run(render_email(
        business_name="Test Co", business_type="plumbing",
        city="Chattanooga", demo_url="https://x.com/d",
        phase="PRODUCTION", prospect_email="owner@biz.com",
    )))
    assert "TEST MODE" not in result["body_html"]


def test_render_email_html_escapes_business_name():
    """Business names with HTML special chars must be escaped in body."""
    result = json.loads(run(render_email(
        business_name='<script>alert("xss")</script>',
        business_type="plumbing",
        city="Chattanooga",
        demo_url="https://x.com/d",
        phase="TESTING",
    )))
    assert "<script>" not in result["body_html"]


def test_render_email_all_niches():
    """All 10 PM niche types should render a valid email without errors."""
    niches = [
        "plumbing", "hvac", "electrician", "roofing", "landscaping",
        "pressure washing", "food truck", "handyman", "painting", "pest control",
    ]
    for niche in niches:
        result = json.loads(run(render_email(
            business_name=f"Test {niche.title()} Co",
            business_type=niche,
            city="Chattanooga",
            demo_url="https://example.com/demo",
            phase="TESTING",
        )))
        assert result["word_count"] > 0, f"Empty email for niche={niche}"
        assert "body_html" in result


def test_count_words_excludes_test_banner():
    """Word count must not include test banner text."""
    with_banner = (
        '<div style="background:#fff3cd;border:1px solid #ffc107;padding:10px;">'
        '⚠️ TEST MODE — This email would normally go to: test@test.com<br>'
        'Business: Test Co | Phase: TESTING</div>'
        '<p>Hi there, this is a short email.</p>'
    )
    count = _count_words(with_banner)
    # Only "Hi there, this is a short email." should count (~7 words)
    assert count <= 10


def test_validate_email_flags_spam_phrases():
    """Spammy phrases should fail validation."""
    result = json.loads(run(validate_email_draft(
        subject="Limited time offer for Smith Plumbing",
        body_html=(
            "<p>LIMITED TIME! 100% GUARANTEED RESULTS! Act now! "
            "<a href='https://example.com/demo'>https://example.com/demo</a></p>"
            "<p>Smith Plumbing should take a look.</p>"
        ),
        demo_url="https://example.com/demo",
        business_name="Smith Plumbing",
    )))
    assert "no_spammy_phrases" in result["issues"]
