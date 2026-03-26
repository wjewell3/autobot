import os
import httpx
import json

def post_pr_to_slack(webhook_url: str, pr_url: str, title: str, channel: str = None):
    text = f"Hardening bot created a PR: {title}\n{pr_url}\nReview and merge to apply. Reply with /apply-pr <number> when ready."
    payload = {"text": text}
    if channel:
        payload["channel"] = channel
    r = httpx.post(webhook_url, json=payload, timeout=10)
    r.raise_for_status()
    return r.text
