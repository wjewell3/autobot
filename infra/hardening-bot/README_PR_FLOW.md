PR flow & rollback
-------------------

1. Hardening bot generates a proposal (e.g., `infra/hardening-bot/proposals/pinned-images.yaml`).
2. Call `POST /create-pr` on the hardening-bot. It will:
   - create a branch `hardening/image-pins-<ts>`
   - commit `infra/hardening-bot/proposals/pinned-images.yaml`
   - push the branch and open a GitHub PR
   - post a Slack message (if `SLACK_WEBHOOK_URL` is configured)

Apply & rollback
-----------------
- To apply after human review: merge the PR (preferred GitOps). Optionally call `POST /apply-pr?pr_number=<n>` if `ALLOW_AUTO_APPLY=true` is set in the bot environment.
- The bot runs `kubectl apply --dry-run=server` before applying. If dry-run fails it aborts.
- Rollback plan (manual):
  - `kubectl rollout undo deployment/<name> -n <namespace>` for affected deployments
  - use `kubectl get events -n <namespace>` and `kubectl logs -n <namespace> <pod>` to debug

Security notes
--------------
- `GITHUB_TOKEN` must be set for Git operations. Use a least-privilege token scoped to the repository.
- `SLACK_WEBHOOK_URL` is optional and posts PRs to Slack.
- `ALLOW_AUTO_APPLY` must be explicitly enabled to allow automated cluster applies.
