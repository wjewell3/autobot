"""
slack_poster.py — MCP tools for posting HITL approval requests to Slack.

Add this to your existing search-tool-server or gmail-tool-server,
OR deploy as its own hitl-tool-server using the standard FastMCP template.

Env vars (add to the target deployment's K8s secret):
  SLACK_BOT_TOKEN         — xoxb-...
  SLACK_HITL_CHANNEL_ID   — C0XXXXXXX (channel ID, not name)
  SLACK_ESCALATION_CHANNEL_ID — defaults to SLACK_HITL_CHANNEL_ID
  HITL_WEBHOOK_URL        — https://autobot-chi-tawny.vercel.app/api/hitl
                            (used in escalation re-posts so agents know where acks go)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

log = logging.getLogger("slack-poster")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_HITL_CHANNEL_ID = os.environ["SLACK_HITL_CHANNEL_ID"]
SLACK_ESCALATION_CHANNEL_ID = os.getenv(
    "SLACK_ESCALATION_CHANNEL_ID", SLACK_HITL_CHANNEL_ID
)

# Timeout seconds per severity level
# low   → auto-approve after timeout (non-blocking work)
# medium → escalate to escalation channel
# high   → auto-reject (potentially destructive action)
TIMEOUTS = {"low": 30 * 60, "medium": 15 * 60, "high": 5 * 60}
TIMEOUT_ACTIONS = {"low": "approved", "medium": "escalated", "high": "rejected"}

mcp = FastMCP(
    "hitl-tool-server",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# ---------------------------------------------------------------------------
# Slack API helpers
# ---------------------------------------------------------------------------

async def slack_post(endpoint: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://slack.com/api/{endpoint}",
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        return data


async def post_approval_message(
    channel_id: str,
    request_id: str,
    requesting_agent: str,
    task_context: str,
    proposed_action: str,
    severity: str,
    timeout_seconds: int,
) -> str:
    """Post the HITL approval message with buttons. Returns message timestamp."""

    severity_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(severity, "⚪")

    # Value embedded in each button so the webhook knows what to resume
    button_value = json.dumps({
        "request_id": request_id,
        "context": {
            "requesting_agent": requesting_agent,
            "task_context": task_context,
            "proposed_action": proposed_action,
        },
    })

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🔔 *HITL Approval Required*\n"
                    f"*Agent:* `{requesting_agent}`\n"
                    f"*Severity:* {severity_emoji} {severity.upper()}\n\n"
                    f"*Task:* {task_context}\n"
                    f"*Proposed Action:* {proposed_action}"
                ),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Request ID: `{request_id}` | Timeout: {timeout_seconds // 60}min",
                }
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "action_id": "approved",
                    "value": button_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "style": "danger",
                    "action_id": "rejected",
                    "value": button_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⬆️ Escalate"},
                    "action_id": "escalated",
                    "value": button_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Request Changes"},
                    "action_id": "request_changes",
                    "value": button_value,
                },
            ],
        },
    ]

    data = await slack_post("chat.postMessage", {"channel": channel_id, "blocks": blocks})
    return data["ts"]


async def handle_timeout(
    request_id: str,
    channel_id: str,
    message_ts: str,
    severity: str,
    requesting_agent: str,
    task_context: str,
    proposed_action: str,
    timeout_seconds: int,
):
    """
    Called after timeout expires. Auto-resolves based on severity:
      low    → auto-approve  (safe to proceed)
      medium → escalate      (re-post to escalation channel with @here)
      high   → auto-reject   (fail safe)
    """
    await asyncio.sleep(timeout_seconds)

    auto_outcome = TIMEOUT_ACTIONS[severity]
    log.info(f"Timeout for {request_id}: auto-{auto_outcome}")

    # Update original message
    timeout_note = {
        "approved": "⏱ Auto-approved after timeout (low severity)",
        "escalated": "⏱ Escalated after timeout — no response received",
        "rejected":  "⏱ Auto-rejected after timeout (high severity — fail safe)",
    }[auto_outcome]

    try:
        await slack_post("chat.update", {
            "channel": channel_id,
            "ts": message_ts,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"🔔 *HITL Approval Required* _(resolved)_\n"
                            f"*Agent:* `{requesting_agent}`\n"
                            f"*Task:* {task_context}\n"
                            f"*Proposed Action:* {proposed_action}"
                        ),
                    },
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": timeout_note}],
                },
            ],
        })
    except Exception as e:
        log.error(f"Failed to update timed-out message: {e}")

    # For escalation, re-post to escalation channel with @here
    if auto_outcome == "escalated" and SLACK_ESCALATION_CHANNEL_ID != channel_id:
        button_value = json.dumps({
            "request_id": request_id,
            "context": {
                "requesting_agent": requesting_agent,
                "task_context": task_context,
                "proposed_action": proposed_action,
            },
        })
        try:
            await slack_post("chat.postMessage", {
                "channel": SLACK_ESCALATION_CHANNEL_ID,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"<!here> 🚨 *Escalated HITL — No response in {timeout_seconds // 60}min*\n"
                                f"*Agent:* `{requesting_agent}`\n"
                                f"*Task:* {task_context}\n"
                                f"*Proposed Action:* {proposed_action}"
                            ),
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "✅ Approve"},
                                "style": "primary",
                                "action_id": "approved",
                                "value": button_value,
                            },
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "❌ Reject"},
                                "style": "danger",
                                "action_id": "rejected",
                                "value": button_value,
                            },
                        ],
                    },
                ],
            })
        except Exception as e:
            log.error(f"Failed to post escalation message: {e}")


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def request_approval(
    task_context: str,
    proposed_action: str,
    severity: str,
    requesting_agent: str,
) -> str:
    """
    Post an approval request to #hitl-approvals in Slack.
    The agent should stop after calling this and wait to be resumed
    via a HITL_RESUME message from the commander.

    Args:
        task_context:     What the agent is currently doing (e.g. "Finding business targets in Nashville")
        proposed_action:  The specific action requiring approval (e.g. "Send cold email to 47 contacts")
        severity:         "low" | "medium" | "high"
                          low    = auto-approve after 30min if no response
                          medium = escalate after 15min if no response
                          high   = auto-reject after 5min if no response (fail safe)
        requesting_agent: Name of the calling agent (e.g. "prospecting-agent")

    Returns:
        request_id to include in any follow-up context
    """
    severity = severity.lower()
    if severity not in TIMEOUTS:
        severity = "medium"

    request_id = str(uuid.uuid4())[:8]
    timeout_seconds = TIMEOUTS[severity]

    log.info(f"HITL request {request_id} from {requesting_agent} (severity={severity})")

    # Post the message
    message_ts = await post_approval_message(
        channel_id=SLACK_HITL_CHANNEL_ID,
        request_id=request_id,
        requesting_agent=requesting_agent,
        task_context=task_context,
        proposed_action=proposed_action,
        severity=severity,
        timeout_seconds=timeout_seconds,
    )

    # Schedule timeout handler in background (fire-and-forget)
    asyncio.create_task(
        handle_timeout(
            request_id=request_id,
            channel_id=SLACK_HITL_CHANNEL_ID,
            message_ts=message_ts,
            severity=severity,
            requesting_agent=requesting_agent,
            task_context=task_context,
            proposed_action=proposed_action,
            timeout_seconds=timeout_seconds,
        )
    )

    return (
        f"Approval request posted to Slack (request_id={request_id}, severity={severity}).\n"
        f"Timeout: {timeout_seconds // 60}min → will auto-{TIMEOUT_ACTIONS[severity]}.\n"
        f"STOP here and do not proceed until you receive a HITL_RESUME message."
    )


@mcp.tool()
async def post_notification(
    channel: str,
    message: str,
    requesting_agent: str,
) -> str:
    """
    Post a plain notification to a Slack channel (no approval needed).
    Use for status updates, alerts, or informational messages.

    Args:
        channel:          Channel ID (e.g. C0XXXXXXX) or name (e.g. agent-workers)
        message:          Message text (supports Slack mrkdwn formatting)
        requesting_agent: Name of the calling agent
    """
    await slack_post("chat.postMessage", {
        "channel": channel,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"From: `{requesting_agent}`"}
                ],
            },
        ],
    })
    return f"Notification posted to {channel}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    import anyio

    PORT = int(os.getenv("HITL_TOOL_PORT", "8091"))
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    anyio.run(uvicorn.Server(config).serve)