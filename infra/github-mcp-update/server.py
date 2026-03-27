from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from typing import Optional
import json, os, base64, httpx

mcp = FastMCP("github_mcp", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
BASE = "https://api.github.com"

class CreateRepoInput(BaseModel):
    name: str = Field(description="Repo name, use hyphens not spaces")
    description: Optional[str] = Field(default="")
    private: Optional[bool] = Field(default=False)

class PushFileInput(BaseModel):
    repo: str = Field(description="owner/repo format e.g. wjewell3/my-site")
    path: str = Field(description="File path e.g. index.html")
    content: str = Field(description="Full file content")
    message: str = Field(description="Commit message")
    branch: Optional[str] = Field(default="main", description="Branch to push to (default: main)")

class RepoInput(BaseModel):
    repo: str = Field(description="owner/repo format")

class EmptyInput(BaseModel):
    pass

class CreateBranchInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    branch: str = Field(description="New branch name e.g. hardening/pin-images-1234")
    from_branch: Optional[str] = Field(default="main", description="Source branch to branch from (default: main)")

class CreatePRInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    title: str = Field(description="PR title")
    body: str = Field(description="PR description (markdown)")
    head: str = Field(description="Branch containing changes")
    base: Optional[str] = Field(default="main", description="Target branch (default: main)")

class CreateIssueInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    title: str = Field(description="Issue title")
    body: Optional[str] = Field(default="", description="Issue body (markdown)")
    labels: Optional[list[str]] = Field(default=[], description="Labels e.g. ['agent:pm-agent', 'priority:high']")
    assignees: Optional[list[str]] = Field(default=[], description="GitHub usernames to assign")

class ListIssuesInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    state: Optional[str] = Field(default="open", description="Filter: open, closed, or all")
    labels: Optional[str] = Field(default="", description="Comma-separated label filter e.g. 'agent:pm-agent,priority:high'")
    per_page: Optional[int] = Field(default=30, description="Results per page (max 100)")

class IssueInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    issue_number: int = Field(description="Issue number")

class UpdateIssueInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    issue_number: int = Field(description="Issue number")
    title: Optional[str] = Field(default=None, description="New title")
    body: Optional[str] = Field(default=None, description="New body")
    state: Optional[str] = Field(default=None, description="open or closed")
    labels: Optional[list[str]] = Field(default=None, description="Replace all labels")
    assignees: Optional[list[str]] = Field(default=None, description="Replace all assignees")

class AddCommentInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    issue_number: int = Field(description="Issue number")

class MergePRInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    pull_number: int = Field(description="PR number to merge")
    merge_method: Optional[str] = Field(default="squash", description="merge, squash, or rebase")

class ListPRsInput(BaseModel):
    repo: str = Field(description="owner/repo format")
    state: Optional[str] = Field(default="open", description="open, closed, or all")
    per_page: Optional[int] = Field(default=30, description="Results per page (max 100)")
    body: str = Field(description="Comment body (markdown)")

@mcp.tool(name="github_list_repos", annotations={"readOnlyHint": True})
async def github_list_repos(params: EmptyInput) -> str:
    """List GitHub repos for authenticated user."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE}/user/repos?per_page=30&sort=updated", headers=HEADERS)
            r.raise_for_status()
            repos = [{"name": x["name"], "url": x["html_url"], "has_pages": x.get("has_pages")} for x in r.json()]
        return json.dumps(repos, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_create_repo", annotations={"destructiveHint": False})
async def github_create_repo(params: CreateRepoInput) -> str:
    """Create a new GitHub repo. Returns full_name (owner/repo) needed for other tools."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}/user/repos", headers=HEADERS, json={"name": params.name, "description": params.description, "private": params.private, "auto_init": True})
            r.raise_for_status()
            data = r.json()
        print(f"[github_create_repo] created={data['full_name']}")
        return json.dumps({"name": data["name"], "full_name": data["full_name"], "url": data["html_url"]}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_push_file", annotations={"destructiveHint": True, "idempotentHint": True})
async def github_push_file(params: PushFileInput) -> str:
    """Create or update a file in a GitHub repo. Handles SHA automatically."""
    try:
        content_b64 = base64.b64encode(params.content.encode()).decode()
        async with httpx.AsyncClient(timeout=15) as client:
            check = await client.get(f"{BASE}/repos/{params.repo}/contents/{params.path}?ref={params.branch}", headers=HEADERS)
            payload = {"message": params.message, "content": content_b64, "branch": params.branch}
            if check.status_code == 200:
                payload["sha"] = check.json()["sha"]
            r = await client.put(f"{BASE}/repos/{params.repo}/contents/{params.path}", headers=HEADERS, json=payload)
            r.raise_for_status()
            data = r.json()
        print(f"[github_push_file] repo={params.repo} path={params.path} branch={params.branch}")
        return json.dumps({"path": params.path, "commit": data.get("commit",{}).get("sha","")}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_enable_pages", annotations={"idempotentHint": True})
async def github_enable_pages(params: RepoInput) -> str:
    """Enable GitHub Pages on main branch. Site goes live at https://owner.github.io/repo"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}/repos/{params.repo}/pages", headers=HEADERS, json={"source": {"branch": "main", "path": "/"}})
            data = r.json()
        print(f"[github_enable_pages] repo={params.repo}")
        return json.dumps({"url": data.get("html_url",""), "status": data.get("status","")}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_get_pages_url", annotations={"readOnlyHint": True})
async def github_get_pages_url(params: RepoInput) -> str:
    """Get GitHub Pages URL and status. May take 1-2 minutes to go live after enabling."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE}/repos/{params.repo}/pages", headers=HEADERS)
            data = r.json()
        return json.dumps({"url": data.get("html_url",""), "status": data.get("status",""), "live": data.get("status")=="built"}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_create_branch", annotations={"destructiveHint": False})
async def github_create_branch(params: CreateBranchInput) -> str:
    """Create a new branch in a GitHub repo from an existing branch."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get the SHA of the source branch
            r = await client.get(f"{BASE}/repos/{params.repo}/git/ref/heads/{params.from_branch}", headers=HEADERS)
            r.raise_for_status()
            sha = r.json()["object"]["sha"]
            # Create the new branch
            r2 = await client.post(f"{BASE}/repos/{params.repo}/git/refs", headers=HEADERS, json={
                "ref": f"refs/heads/{params.branch}",
                "sha": sha
            })
            r2.raise_for_status()
            data = r2.json()
        print(f"[github_create_branch] repo={params.repo} branch={params.branch} from={params.from_branch}")
        return json.dumps({"ref": data["ref"], "sha": data["object"]["sha"]}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_create_pr", annotations={"destructiveHint": False})
async def github_create_pr(params: CreatePRInput) -> str:
    """Create a pull request. Returns PR URL and number for review."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}/repos/{params.repo}/pulls", headers=HEADERS, json={
                "title": params.title,
                "body": params.body,
                "head": params.head,
                "base": params.base
            })
            r.raise_for_status()
            data = r.json()
        print(f"[github_create_pr] repo={params.repo} pr=#{data['number']}")
        return json.dumps({
            "number": data["number"],
            "url": data["html_url"],
            "state": data["state"],
            "title": data["title"]
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_create_issue", annotations={"destructiveHint": False})
async def github_create_issue(params: CreateIssueInput) -> str:
    """Create a GitHub issue. Use labels for agent tracking e.g. 'agent:pm-agent'."""
    try:
        payload = {"title": params.title, "body": params.body}
        if params.labels:
            payload["labels"] = params.labels
        if params.assignees:
            payload["assignees"] = params.assignees
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}/repos/{params.repo}/issues", headers=HEADERS, json=payload)
            r.raise_for_status()
            data = r.json()
        print(f"[github_create_issue] repo={params.repo} issue=#{data['number']}")
        return json.dumps({
            "number": data["number"],
            "url": data["html_url"],
            "title": data["title"],
            "state": data["state"],
            "labels": [l["name"] for l in data.get("labels", [])]
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_list_issues", annotations={"readOnlyHint": True})
async def github_list_issues(params: ListIssuesInput) -> str:
    """List issues in a repo. Filter by state and labels."""
    try:
        query = f"state={params.state}&per_page={params.per_page}"
        if params.labels:
            query += f"&labels={params.labels}"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE}/repos/{params.repo}/issues?{query}", headers=HEADERS)
            r.raise_for_status()
            issues = [{
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "labels": [l["name"] for l in i.get("labels", [])],
                "assignees": [a["login"] for a in i.get("assignees", [])],
                "created_at": i["created_at"],
                "updated_at": i["updated_at"]
            } for i in r.json() if "pull_request" not in i]
        return json.dumps(issues, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_get_issue", annotations={"readOnlyHint": True})
async def github_get_issue(params: IssueInput) -> str:
    """Get details of a specific issue including body and comments."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE}/repos/{params.repo}/issues/{params.issue_number}", headers=HEADERS)
            r.raise_for_status()
            i = r.json()
            rc = await client.get(f"{BASE}/repos/{params.repo}/issues/{params.issue_number}/comments?per_page=20", headers=HEADERS)
            comments = [{"author": c["user"]["login"], "body": c["body"], "created_at": c["created_at"]} for c in rc.json()] if rc.status_code == 200 else []
        return json.dumps({
            "number": i["number"],
            "title": i["title"],
            "body": i.get("body", ""),
            "state": i["state"],
            "labels": [l["name"] for l in i.get("labels", [])],
            "assignees": [a["login"] for a in i.get("assignees", [])],
            "created_at": i["created_at"],
            "updated_at": i["updated_at"],
            "comments": comments
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_update_issue", annotations={"destructiveHint": False, "idempotentHint": True})
async def github_update_issue(params: UpdateIssueInput) -> str:
    """Update an issue's title, body, state, labels, or assignees."""
    try:
        payload = {}
        if params.title is not None:
            payload["title"] = params.title
        if params.body is not None:
            payload["body"] = params.body
        if params.state is not None:
            payload["state"] = params.state
        if params.labels is not None:
            payload["labels"] = params.labels
        if params.assignees is not None:
            payload["assignees"] = params.assignees
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.patch(f"{BASE}/repos/{params.repo}/issues/{params.issue_number}", headers=HEADERS, json=payload)
            r.raise_for_status()
            data = r.json()
        print(f"[github_update_issue] repo={params.repo} issue=#{params.issue_number}")
        return json.dumps({
            "number": data["number"],
            "title": data["title"],
            "state": data["state"],
            "labels": [l["name"] for l in data.get("labels", [])]
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_add_comment", annotations={"destructiveHint": False})
async def github_add_comment(params: AddCommentInput) -> str:
    """Add a comment to an issue. Agents use this for status updates."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}/repos/{params.repo}/issues/{params.issue_number}/comments", headers=HEADERS, json={"body": params.body})
            r.raise_for_status()
            data = r.json()
        print(f"[github_add_comment] repo={params.repo} issue=#{params.issue_number}")
        return json.dumps({"id": data["id"], "url": data["html_url"]}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_merge_pr", annotations={"destructiveHint": True})
async def github_merge_pr(params: MergePRInput) -> str:
    """Merge a pull request. Use after HITL approval. Supports squash, merge, or rebase."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.put(
                f"{BASE}/repos/{params.repo}/pulls/{params.pull_number}/merge",
                headers=HEADERS,
                json={"merge_method": params.merge_method}
            )
            r.raise_for_status()
            data = r.json()
        print(f"[github_merge_pr] repo={params.repo} pr=#{params.pull_number} method={params.merge_method}")
        return json.dumps({"merged": data.get("merged", False), "sha": data.get("sha", ""), "message": data.get("message", "")}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp.tool(name="github_list_prs", annotations={"readOnlyHint": True})
async def github_list_prs(params: ListPRsInput) -> str:
    """List pull requests on a repo. Use to check for existing open PRs before creating duplicates."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{BASE}/repos/{params.repo}/pulls",
                headers=HEADERS,
                params={"state": params.state, "per_page": params.per_page}
            )
            r.raise_for_status()
            prs = r.json()
        result = [{"number": pr["number"], "title": pr["title"], "head": pr["head"]["ref"], "state": pr["state"], "url": pr["html_url"]} for pr in prs]
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    import uvicorn
    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="0.0.0.0", port=8087, log_level="info")
    server = uvicorn.Server(config)
    import anyio
    anyio.run(server.serve)
