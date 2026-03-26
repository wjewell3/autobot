import os
import subprocess
import time
import json
import re
from pathlib import Path
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]

def _run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    return r.stdout.strip()

def create_branch_and_commit(proposal_path: Path, branch_name: str, commit_msg: str):
    # create branch, add file, commit
    _run(["git", "fetch", "origin"])
    _run(["git", "checkout", "-b", branch_name])
    _run(["git", "add", str(proposal_path)])
    _run(["git", "commit", "-m", commit_msg])

def push_branch_with_token(branch_name: str, token: str):
    origin = _run(["git", "remote", "get-url", "origin"]) 
    m = re.match(r"https://(github.com/.+)", origin)
    if not m:
        raise RuntimeError("origin URL not https://github.com/... . Cannot push with token helper")
    repo_path = m.group(1)
    remote_with_token = f"https://{token}@{repo_path}"
    _run(["git", "push", "-u", remote_with_token, branch_name])

def open_github_pr(branch_name: str, title: str, body: str, token: str):
    # determine owner/repo from origin
    origin = _run(["git", "remote", "get-url", "origin"]) 
    m = re.match(r"https://github.com/(?P<ownerrepo>.+?)(?:\.git)?$", origin)
    if not m:
        raise RuntimeError("cannot parse origin URL for owner/repo")
    ownerrepo = m.group("ownerrepo")
    api = f"https://api.github.com/repos/{ownerrepo}/pulls"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    data = {"title": title, "head": branch_name, "base": "main", "body": body}
    r = httpx.post(api, headers=headers, json=data)
    if r.status_code >= 300:
        raise RuntimeError(f"GitHub PR creation failed: {r.status_code} {r.text}")
    return r.json()

def create_pr_from_proposal(proposals_json_path: Path, github_token: str, slack_notify_fn=None):
    ts = int(time.time())
    branch = f"hardening/image-pins-{ts}"
    commit_msg = f"chore: pin images (hardening) {ts}"
    # convert JSON proposals to a YAML patch file under infra/proposals/
    p = Path(proposals_json_path)
    if not p.exists():
        raise RuntimeError("proposals file not found")
    obj = json.loads(p.read_text())
    yaml_path = p.parent / "pinned-images.yaml"
    yaml.safe_dump(obj, yaml_path.open("w"), sort_keys=False)
    create_branch_and_commit(yaml_path, branch, commit_msg)
    push_branch_with_token(branch, github_token)
    title = "hardening: pin images (automated)"
    body = "This PR pins currently running images to their digests. Review and merge to apply. Run CI/dry-run before apply.\n\nRollback: `kubectl rollout undo deployment/<name> -n <ns>` for affected deployments.`"
    pr = open_github_pr(branch, title, body, github_token)
    if slack_notify_fn:
        slack_notify_fn(pr["html_url"], title)
    return pr
