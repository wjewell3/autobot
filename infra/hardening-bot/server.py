from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from fastapi import FastAPI
import subprocess
import json
import os
from pathlib import Path
from .git_pr import create_pr_from_proposal
from .slack_notify import post_pr_to_slack

# Minimal FastMCP / FastAPI scaffold for Hardening AI-bot
mcp = FastMCP("hardening-bot", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=False
))

app = mcp.streamable_http_app()

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/scan-images")
async def scan_images():
    # Run the scanner script and return the generated JSON
    script = os.path.join(os.path.dirname(__file__), "scan_images.py")
    try:
        proc = subprocess.run(["python", script], capture_output=True, text=True, check=False)
    except Exception as e:
        return {"error": str(e)}
    proposals_file = os.path.join(os.path.dirname(__file__), "proposals", "image-pins.json")
    if os.path.exists(proposals_file):
        with open(proposals_file, "r") as f:
            data = json.load(f)
        return {"stdout": proc.stdout, "proposals": data}
    return {"stdout": proc.stdout, "message": "no proposals generated"}


@app.post("/create-pr")
async def create_pr():
    # requires env: GITHUB_TOKEN, SLACK_WEBHOOK_URL (optional)
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        return {"error": "GITHUB_TOKEN not set"}
    proposals_file = os.path.join(os.path.dirname(__file__), "proposals", "image-pins.json")
    if not os.path.exists(proposals_file):
        # generate first
        subprocess.run(["python", os.path.join(os.path.dirname(__file__), "scan_images.py")])
    def slack_fn(pr_url, title):
        webhook = os.environ.get("SLACK_WEBHOOK_URL")
        if not webhook:
            return
        try:
            post_pr_to_slack(webhook, pr_url, title)
        except Exception:
            pass
    pr = create_pr_from_proposal(proposals_file, github_token, slack_notify_fn=slack_fn)
    return {"pr": pr}

@app.post("/apply-pr")
async def apply_pr(pr_number: int):
    # Apply PR changes to cluster after dry-run; requires GITHUB_TOKEN and ALLOW_AUTO_APPLY=true
    github_token = os.environ.get("GITHUB_TOKEN")
    allow = os.environ.get("ALLOW_AUTO_APPLY", "false").lower() == "true"
    if not github_token:
        return {"error": "GITHUB_TOKEN not set"}
    if not allow:
        return {"error": "Auto-apply disabled. Set ALLOW_AUTO_APPLY=true to enable"}
    # determine owner/repo
    origin = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    import re
    m = re.match(r"https://github.com/(?P<ownerrepo>.+?)(?:\.git)?$", origin)
    if not m:
        return {"error": "cannot parse origin"}
    ownerrepo = m.group("ownerrepo")
    api = f"https://api.github.com/repos/{ownerrepo}/pulls/{pr_number}/files"
    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github+json"}
    r = httpx.get(api, headers=headers)
    if r.status_code >= 300:
        return {"error": r.text}
    files = r.json()
    # apply each file: fetch raw contents and kubectl apply --dry-run=server
    applied = []
    for f in files:
        raw_url = f["raw_url"]
        content = httpx.get(raw_url).content
        # dry-run
        p = subprocess.run(["kubectl", "apply", "-f", "-", "--dry-run=server"], input=content, capture_output=True)
        if p.returncode != 0:
            return {"error": "dry-run failed", "stdout": p.stdout.decode(), "stderr": p.stderr.decode()}
        # apply for real
        p2 = subprocess.run(["kubectl", "apply", "-f", "-"], input=content, capture_output=True)
        if p2.returncode != 0:
            return {"error": "apply failed", "stdout": p2.stdout.decode(), "stderr": p2.stderr.decode()}
        applied.append(f["filename"])
    return {"applied": applied}

if __name__ == '__main__':
    import uvicorn, anyio
    config = uvicorn.Config(app, host="0.0.0.0", port=8085, log_level="info")
    anyio.run(uvicorn.Server(config).serve)
