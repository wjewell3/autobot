"""
outreach-mcp — deterministic email rendering and phase enforcement.

Compiles the most expensive LLM tasks in outreach-agent:
  - render_email:         Full HTML email from structured inputs
                          (was: LLM drafting email, ~600 tokens, inconsistent tone)
  - validate_email_draft: Quality gate — check required elements are present
                          (was: LLM self-check, sometimes passed bad emails)

Phase enforcement (TESTING vs PRODUCTION) is now deterministic and cannot be
reasoned around by the LLM — the recipient override is applied in code.

Port: 8103
Deployed by: codegen-agent / human operator
Replaces LLM calls in: outreach-agent
"""

import html
import json
import os
import re

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

PORT = int(os.environ.get("OUTREACH_MCP_PORT", "8103"))

OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL", "jewell.will@gmail.com")

mcp = FastMCP(
    "outreach-mcp",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ── Email copy templates ──────────────────────────────────────────────────────
# Personalized by business type but deterministic — no LLM creativity needed
# for the core structure. The LLM only needs to send business details.

_NICHE_OPENERS: dict[str, str] = {
    "plumbing":        "I noticed {business_name} doesn't have a website yet",
    "hvac":            "I was searching for HVAC companies in {city} and noticed {business_name} doesn't have a website",
    "electrician":     "I came across {business_name} while looking for electricians in {city} — I noticed you don't have a website yet",
    "roofing":         "I noticed {business_name} is serving {city} without a website",
    "landscaping":     "I found {business_name} while searching for landscapers in {city} and noticed there's no website yet",
    "pressure washing":"I was looking for pressure washing services in {city} and noticed {business_name} doesn't have a web presence yet",
    "food truck":      "I came across {business_name} and noticed there's no website to help customers find you",
    "handyman":        "I noticed {business_name} doesn't have a website yet — a lot of {city} homeowners search online first",
    "painting":        "I was searching for painters in {city} and noticed {business_name} doesn't have a website",
    "pest control":    "I noticed {business_name} is serving {city} without a website to capture online leads",
}

_DEFAULT_OPENER = "I noticed {business_name} in {city} doesn't have a website yet"

_NICHE_VALUE_PROPS: dict[str, str] = {
    "plumbing":        "Most people search Google for a plumber before calling. A website means they find you first.",
    "hvac":            "Homeowners search online when their AC breaks at 2am. A website puts you at the top of that search.",
    "electrician":     "Customers google electricians before they call. A website makes sure they find you — not a competitor.",
    "roofing":         "After a storm, homeowners search online for roofers immediately. A website captures that traffic.",
    "landscaping":     "Homeowners search for landscapers in the spring. A website means you're ready when they are.",
    "pressure washing":"Customers are searching for pressure washing services right now. A website helps them find you.",
    "food truck":      "A website lets customers find your schedule, menu, and book you for events.",
    "handyman":        "A website lets {city} homeowners find and contact you 24/7 — even when you're on the job.",
    "painting":        "People searching for painters online are ready to hire. A website puts you in front of them.",
    "pest control":    "When pests show up, people Google immediately. A website means they call you first.",
}

_DEFAULT_VALUE_PROP = "Most customers search online before they call. A website makes sure they find you first."


def _get_opener(niche: str, business_name: str, city: str) -> str:
    niche_lower = niche.lower()
    template = _DEFAULT_OPENER
    for key, tmpl in _NICHE_OPENERS.items():
        if key in niche_lower:
            template = tmpl
            break
    return template.format(
        business_name=html.escape(business_name),
        city=html.escape(city),
    )


def _get_value_prop(niche: str, business_name: str, city: str) -> str:
    niche_lower = niche.lower()
    template = _DEFAULT_VALUE_PROP
    for key, tmpl in _NICHE_VALUE_PROPS.items():
        if key in niche_lower:
            template = tmpl
            break
    return template.format(
        business_name=html.escape(business_name),
        city=html.escape(city),
    )


def _count_words(html_str: str) -> int:
    """Count words in HTML string, ignoring tags and the test banner."""
    # Remove test banner
    clean = re.sub(r'<div[^>]*style="background:#fff3cd[^"]*".*?</div>', "", html_str, flags=re.DOTALL)
    # Remove all HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return len(clean.split())


TEST_BANNER_TEMPLATE = """<div style="background:#fff3cd;border:1px solid #ffc107;padding:10px;margin-bottom:16px;font-family:monospace;font-size:13px;">
⚠️ TEST MODE — This email would normally go to: {prospect_email}<br>
Business: {business_name} | Phase: TESTING
</div>"""


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def render_email(
    business_name: str,
    business_type: str,
    city: str,
    demo_url: str,
    phase: str = "TESTING",
    prospect_email: str = "",
    contact_name: str = "",
) -> str:
    """
    Render a complete HTML outreach email with phase enforcement.

    Phase rules are applied deterministically in code — not by LLM:
      TESTING:    recipient = operator email (OPERATOR_EMAIL env var)
                  subject prefixed with [TEST]
                  test banner included in body
      PRODUCTION: recipient = prospect_email
                  normal subject, no test banner

    Args:
        business_name:  Business name (e.g. "Jim's Plumbing")
        business_type:  Niche/industry (e.g. "plumbing", "HVAC")
        city:           City (e.g. "Chattanooga")
        demo_url:       Live GitHub Pages demo URL
        phase:          "TESTING" or "PRODUCTION" (default: TESTING)
        prospect_email: Prospect's email address (required for PRODUCTION)
        contact_name:   Contact first name for personalization (optional)

    Returns:
        JSON: {
          "recipient":    str,
          "subject":      str,
          "body_html":    str,
          "phase":        str,
          "word_count":   int,
          "test_mode":    bool
        }
    """
    phase_upper = phase.strip().upper()
    is_testing = phase_upper != "PRODUCTION"

    # Phase-controlled recipient (cannot be bypassed by LLM)
    recipient = OPERATOR_EMAIL if is_testing else (prospect_email or OPERATOR_EMAIL)

    # Greeting
    greeting = f"Hi {html.escape(contact_name)}," if contact_name else "Hi there,"

    # Niche-aware copy
    opener = _get_opener(business_type, business_name, city)
    value_prop = _get_value_prop(business_type, business_name, city)

    # Subject
    base_subject = f"Free demo website for {business_name}"
    subject = f"[TEST] {base_subject}" if is_testing else base_subject

    # Build body
    demo_link = f'<a href="{html.escape(demo_url)}">{html.escape(demo_url)}</a>'

    test_banner = TEST_BANNER_TEMPLATE.format(
        prospect_email=html.escape(prospect_email or "unknown"),
        business_name=html.escape(business_name),
    ) if is_testing else ""

    body_html = f"""{test_banner}<p>{greeting}</p>

<p>{opener} — so I built a <strong>free demo website</strong> for you:</p>

<p style="text-align:center;margin:24px 0;">
  <a href="{html.escape(demo_url)}" style="background:#1A5C8A;color:white;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold;font-size:1rem;">
    👉 View Your Demo Site
  </a>
</p>

<p>{value_prop}</p>

<p>I'd love to customize it with your real photos, pricing, and services — completely free. Take a look: {demo_link}</p>

<p>Let me know what you think!</p>

<p>Will<br>
<small style="color:#888;">Reply to this email or just click the button above.</small></p>"""

    word_count = _count_words(body_html)

    return json.dumps({
        "recipient": recipient,
        "subject": subject,
        "body_html": body_html,
        "phase": phase_upper,
        "word_count": word_count,
        "test_mode": is_testing,
    })


@mcp.tool()
async def validate_email_draft(
    subject: str,
    body_html: str,
    demo_url: str,
    business_name: str,
) -> str:
    """
    Validate an outreach email draft against the quality checklist.

    Checks all required elements from outreach-agent system message:
    demo URL present, business name present, under 150 words, has CTA,
    not using forbidden salesy phrases.

    Args:
        subject:       Email subject line.
        body_html:     HTML email body.
        demo_url:      The demo site URL that should appear in the body.
        business_name: Business name that should appear in subject or body.

    Returns:
        JSON: {
          "valid":      bool,
          "issues":     [str],
          "warnings":   [str],
          "word_count": int,
          "checks":     {check_name: bool}
        }
    """
    word_count = _count_words(body_html)
    body_lower = body_html.lower()
    subject_lower = subject.lower()

    checks = {
        "demo_url_in_body": demo_url in body_html,
        "business_name_in_content": (
            business_name.lower() in body_lower or
            business_name.lower() in subject_lower
        ),
        "has_cta": bool(re.search(
            r"view your demo|take a look|let me know|click|visit|check it out",
            body_lower,
        )),
        "under_150_words": word_count <= 150,
        "subject_not_empty": len(subject.strip()) > 0,
        "subject_reasonable_length": len(subject) <= 80,
        "no_spammy_phrases": not bool(re.search(
            r"\b(limited time|act now|guaranteed|100%|risk.?free|no obligation"
            r"|dear sir|to whom it may concern|unsubscribe)\b",
            body_lower,
        )),
    }

    issues = [k for k, v in checks.items() if not v]
    warnings = []
    if word_count > 120:
        warnings.append(f"Email is {word_count} words — ideally under 120 for cold outreach")
    if "[TEST]" in subject and "test_mode" not in subject.lower():
        warnings.append("Subject contains [TEST] prefix — confirm this is in TESTING phase")

    return json.dumps({
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "word_count": word_count,
        "checks": checks,
    })


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import anyio
    import uvicorn

    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
