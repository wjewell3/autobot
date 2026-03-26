Hardening AI-bot
=================

Purpose
-------
This scaffold provides a small Hardening AI-bot (an in-cluster MCP-style FastAPI service) that:

- Scans the cluster for running images and their digests
- Scans repository YAML manifests for floating image tags
- Produces a proposal mapping to pin tags to `@sha256:` digests
- Exposes a simple HTTP endpoint to trigger scans and return proposals

Design notes
------------
- The bot runs in read-only mode by default: it only generates proposals (JSON/YAML). It does not modify cluster or Git history.
- Proposals are intended to be reviewed and merged by a human (HITL). The PR/merge/apply flow is outside this scaffold.
- For in-cluster MCP servers, DNS rebinding protection is disabled in the example server (see `server.py`).

Quick run (local, requires `kubectl` access and Python 3.11+)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python server.py
# then visit: http://0.0.0.0:8085/scan-images
```

Files
-----
- `server.py` - minimal FastAPI/MCP-compatible server exposing `/scan-images`
- `scan_images.py` - scanner that reads running pod digests and repo manifests and writes a proposal JSON
- `requirements.txt` - Python deps
