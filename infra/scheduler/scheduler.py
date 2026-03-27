"""
scheduler.py — Sends periodic autonomous tasks to commander via A2A.

Runs as a K8s CronJob. Each invocation sends one task based on the
TASK_TYPE environment variable.

Tasks:
  cso-security-audit  — CSO reviews agent permissions + tool drift
  pm-full-pipeline    — PM runs full cycle: prospect → site → outreach (HITL-gated)
  coo-status-check    — COO checks for operational drift
  cfo-resource-check  — CFO reviews token usage, cluster resources, action budgets
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
    "pm-full-pipeline": (
        "PIPELINE CYCLE (scheduled): "
        "Route to PM. Ask PM to run the full business pipeline: "
        "1) Check the current backlog for any incomplete tasks (businesses found but no site yet, "
        "   or sites built but no outreach yet). Complete those first. "
        "2) If the backlog is clear, start a new prospecting batch: "
        "   find 3-5 businesses needing websites in Nashville, TN — focus on service trades "
        "   (plumbing, HVAC, electricians, landscaping). "
        "3) For each business found, delegate to site-builder-agent to create a demo GitHub Pages site. "
        "4) For each site built, delegate to outreach-agent to request HITL approval and send a "
        "   cold outreach email with the demo site URL. "
        "5) Write audit entries for each stage. "
        "The outreach step is HITL-gated — the PM should request approval before sending any email."
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
    "cfo-resource-check": (
        "RESOURCE CHECK (scheduled): "
        "Route to CFO. Ask CFO to: "
        "1) Check current token usage and budget burn rate across all agents. "
        "2) Check cluster resource utilization (CPU, memory) across all pods in kagent namespace. "
        "3) Check action budget status — any agents near their limits? "
        "4) Post a brief resource summary to Slack. Flag anything requiring attention. "
        "5) Write an audit entry with the current resource state. "
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
