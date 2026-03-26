"""
scheduler.py — Sends periodic autonomous tasks to commander via A2A.

Runs as a K8s CronJob. Each invocation sends one task based on the
TASK_TYPE environment variable.

Tasks:
  cso-security-audit  — CSO reviews agent permissions + tool drift
  pm-prospecting      — PM runs a prospecting batch
  coo-status-check    — COO checks for operational drift
"""

import json
import logging
import os
import sys

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("scheduler")

KAGENT_URL = os.getenv(
    "KAGENT_URL",
    "http://commander-agent.kagent.svc.cluster.local:8080",
)
AGENT_NAME = "commander-agent"
NAMESPACE = "kagent"
TASK_TYPE = os.getenv("TASK_TYPE", "cso-security-audit")

TASKS = {
    "cso-security-audit": (
        "SECURITY AUDIT REQUEST (scheduled): "
        "Route to CSO. Ask CSO to: "
        "1) List all agents and their current tools. "
        "2) Check for any agent with gmail_send_email (forbidden). "
        "3) Check for agents with tools not in the capability registry. "
        "4) Write an audit entry summarizing findings. "
        "Report the results back."
    ),
    "pm-prospecting": (
        "PROSPECTING TASK (scheduled): "
        "Route to PM. Ask PM to: "
        "1) Check the current backlog for any existing prospecting tasks. "
        "2) If no active prospecting tasks, create a new one: "
        "   find businesses needing websites in Nashville, TN — plumbing industry. "
        "3) Delegate to prospecting-agent. "
        "4) Write audit entries for task creation and completion. "
        "Report the results back."
    ),
    "coo-status-check": (
        "OPERATIONS CHECK (scheduled): "
        "Route to COO. Ask COO to: "
        "1) Read the last 50 audit entries. "
        "2) Check for any agent errors or repeated failures. "
        "3) Check for any agents that haven't been active in the last cycle. "
        "4) Post a brief status summary to Slack. "
        "Report the results back."
    ),
}


def send_task():
    task_message = TASKS.get(TASK_TYPE)
    if not task_message:
        log.error(f"Unknown task type: {TASK_TYPE}. Valid: {list(TASKS.keys())}")
        sys.exit(1)

    log.info(f"Sending scheduled task: {TASK_TYPE}")
    log.info(f"Target: {AGENT_NAME} via {KAGENT_URL}")

    url = f"{KAGENT_URL}/"
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": task_message}],
                "messageId": f"scheduler-{TASK_TYPE}-{int(__import__('time').time())}",
            }
        },
        "id": f"scheduler-{TASK_TYPE}",
    }

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        log.info(f"Response status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result", {})
            parts = result.get("artifacts", [{}])
            if parts:
                for artifact in parts:
                    for part in artifact.get("parts", []):
                        text = part.get("text", "")
                        if text:
                            log.info(f"Agent response: {text[:500]}")
            log.info(f"Task {TASK_TYPE} completed successfully")
        else:
            log.error(f"Task failed: {resp.status_code} — {resp.text[:500]}")
            sys.exit(1)
    except Exception as e:
        log.error(f"Failed to send task: {e}")
        sys.exit(1)


if __name__ == "__main__":
    send_task()
