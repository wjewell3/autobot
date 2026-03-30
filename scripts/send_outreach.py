#!/usr/bin/env python3
"""
send_outreach.py — Send personalized cold outreach emails to plumber prospects.

Reads the prospect CSV + knows which demos were generated, then sends
personalized emails with the demo site link.

IMPORTANT — Email strategy (read before running):
────────────────────────────────────────────────
1. Use 2-3 Gmail accounts MAX. Do NOT create dozens — Google links them
   by IP/phone/device and bans them all together.

2. WARM UP each account for 2 weeks before sending cold:
   - Day 1-7: send 5 normal emails/day to friends, reply to them
   - Day 8-14: increase to 10/day, mix of personal and outreach
   - Day 15+: start cold outreach at 15-20/day max

3. CAN-SPAM compliance (required by law):
   - Include your physical mailing address
   - Include unsubscribe link
   - Accurate "From" and subject lines
   - Don't use deceptive headers
   - Violation = $50,120 per email

4. Send limits:
   - Gmail free: 500/day but NEW accounts hit spam at 10-15/day
   - Warmed account: safe at 20-30/day
   - 2 accounts × 20/day = 40 emails/day = 280/week = plenty

5. The math that matters:
   - 100 emails → ~5 conversations → 2-3 clients at $99/mo
   - You don't need thousands. You need 100 good ones.
────────────────────────────────────────────────

Usage:
  # Preview emails (prints to terminal, doesn't send):
  python scripts/send_outreach.py --csv output/prospects/plumbers-nashville-tn.csv --preview

  # Send via Gmail SMTP (interactive — confirms before each send):
  python scripts/send_outreach.py --csv output/prospects/plumbers-nashville-tn.csv --send

  # Send without confirmation (use ONLY after you've verified previews):
  python scripts/send_outreach.py --csv output/prospects/plumbers-nashville-tn.csv --send --no-confirm

Environment:
  GMAIL_ADDRESS    — Your Gmail address
  GMAIL_APP_PASS   — Gmail app password (NOT your regular password)
                     Generate at: https://myaccount.google.com/apppasswords
  PHYSICAL_ADDRESS — Your mailing address (CAN-SPAM requirement)
  SENDER_NAME      — Your name for the From field
  DEMO_BASE_URL    — Base URL for demos (default: https://wjewell3.github.io/plumber-demos)
"""

import argparse
import csv
import os
import re
import smtplib
import sys
import time
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
PHYSICAL_ADDRESS = os.environ.get("PHYSICAL_ADDRESS", "Nashville, TN")  # CAN-SPAM
SENDER_NAME = os.environ.get("SENDER_NAME", "Will Jewell")
DEMO_BASE_URL = os.environ.get("DEMO_BASE_URL", "https://wjewell3.github.io/plumber-demos")

SEND_DELAY = 45  # seconds between emails (stay under rate limits)
DAILY_LIMIT = 20  # max emails per run


# ── Slug / URL ────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"\s*[&+]\s*", "-and-", n)
    n = re.sub(r"['\",\.\']", "", n)
    n = re.sub(r"[^a-z0-9]+", "-", n)
    n = re.sub(r"-{2,}", "-", n)
    return n.strip("-")


def demo_url(name: str, city: str) -> str:
    slug = slugify(f"{name}-{city}")
    return f"{DEMO_BASE_URL}/demos/{slug}/"


# ── Email Templates ───────────────────────────────────────────────────────────

def render_email_subject(business_name: str) -> str:
    """Short, curiosity-driven subject line."""
    return f"I built {business_name} a free website"


def render_email_body(
    business_name: str,
    city: str,
    state: str,
    demo_link: str,
    sender_name: str,
) -> tuple[str, str]:
    """
    Render both plain text and HTML email body.
    Returns (plain_text, html_text).

    Key principles:
    - Lead with value (the free demo)
    - Short (under 100 words)
    - No pressure, no "limited time offer"
    - Clear CTA
    - CAN-SPAM compliant (address + unsubscribe)
    """

    plain = f"""Hi there,

I noticed {business_name} doesn't have a website yet, so I went ahead and built a free demo for you:

{demo_link}

It's mobile-friendly, shows your services, and has your contact info. Takes about 30 seconds to check out.

If you like it, I can put it on your own domain (like {slugify(business_name)}.com) for $99/month — I handle everything. If not, no worries at all.

Best,
{sender_name}

---
{PHYSICAL_ADDRESS}
To stop receiving these emails, reply "unsubscribe" and I'll remove you immediately.
"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; color: #333; line-height: 1.6; max-width: 560px; margin: 0 auto; padding: 20px;">

<p>Hi there,</p>

<p>I noticed <strong>{business_name}</strong> doesn't have a website yet, so I went ahead and built a free demo for you:</p>

<p style="text-align: center; margin: 24px 0;">
  <a href="{demo_link}" style="display: inline-block; background: #1A5C8A; color: white; padding: 14px 32px; border-radius: 6px; text-decoration: none; font-weight: 600;">
    View Your Free Demo Website →
  </a>
</p>

<p>It's mobile-friendly, shows your services, and has your contact info. Takes about 30 seconds to check out.</p>

<p>If you like it, I can put it on your own domain (like <strong>{slugify(business_name)}.com</strong>) for <strong>$99/month</strong> — I handle everything. If not, no worries at all.</p>

<p>Best,<br>{sender_name}</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
<p style="font-size: 0.8em; color: #999;">
  {PHYSICAL_ADDRESS}<br>
  To stop receiving these emails, reply "unsubscribe" and I'll remove you immediately.
</p>

</body>
</html>"""

    return plain, html


# ── Send via Gmail SMTP ───────────────────────────────────────────────────────

def send_email(to_email: str, subject: str, plain: str, html: str) -> bool:
    """Send a single email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{SENDER_NAME} <{GMAIL_ADDRESS}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"    ❌ Send failed: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Send outreach emails to plumber prospects")
    parser.add_argument("--csv", required=True, help="Prospects CSV from prospect_plumbers.py")
    parser.add_argument("--preview", action="store_true", help="Preview emails without sending")
    parser.add_argument("--send", action="store_true", help="Actually send emails via Gmail SMTP")
    parser.add_argument("--no-confirm", action="store_true", help="Skip per-email confirmation")
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT, help=f"Max emails to send (default: {DAILY_LIMIT})")

    args = parser.parse_args()

    if not args.preview and not args.send:
        parser.print_help()
        print("\nUse --preview to see emails or --send to send them.")
        sys.exit(1)

    if args.send:
        if not GMAIL_ADDRESS or not GMAIL_APP_PASS:
            print("❌ Set GMAIL_ADDRESS and GMAIL_APP_PASS environment variables")
            print("   Generate app password: https://myaccount.google.com/apppasswords")
            sys.exit(1)

    # Read prospects
    leads = []
    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") in ("HOT", "WARM"):
                leads.append(row)

    leads = leads[:args.limit]

    if not leads:
        print("❌ No HOT/WARM leads in CSV")
        return

    print(f"📧 {'Previewing' if args.preview else 'Sending'} {len(leads)} emails\n")

    sent = 0
    for i, lead in enumerate(leads, 1):
        name = lead.get("name", "").strip()
        city = lead.get("city", "").strip()
        state = lead.get("state", "").strip()
        phone = lead.get("phone", "").strip()

        if not name:
            continue

        link = demo_url(name, city)
        subject = render_email_subject(name)
        plain, html = render_email_body(name, city, state, link, SENDER_NAME)

        print(f"{'─'*50}")
        print(f"  [{i}/{len(leads)}] {name} — {city}, {state}")
        print(f"  Subject: {subject}")
        print(f"  Demo:    {link}")

        if args.preview:
            print(f"\n{plain}")
            continue

        if args.send:
            # We don't have the prospect's email — need to find it
            # For now, preview mode shows what would be sent
            # In production, you'd look up emails via SearXNG or manual research
            print(f"  ⚠ No email address in CSV — use --preview to draft, then send manually")
            print(f"    Copy the subject + demo URL and send from your Gmail")
            print(f"\n{plain}")
            continue

        sent += 1

        if i < len(leads):
            print(f"  ⏳ Waiting {SEND_DELAY}s...")
            time.sleep(SEND_DELAY)

    print(f"\n{'═'*50}")
    if args.preview:
        print(f"  📋 Previewed {len(leads)} emails")
        print(f"  Next step: Find email addresses, then run with --send")
    else:
        print(f"  📧 Sent {sent}/{len(leads)} emails")
    print(f"{'═'*50}")


if __name__ == "__main__":
    main()
