/**
 * api/hitl.js — Slack HITL webhook receiver
 *
 * Slack posts button interaction payloads here.
 * We validate the signature, extract the outcome, and fire a new kagent task.
 *
 * Env vars needed in Vercel dashboard:
 *   SLACK_SIGNING_SECRET   — from Slack app settings > Basic Information
 *   SLACK_BOT_TOKEN        — xoxb-... from Slack app settings > OAuth & Permissions
 *   KAGENT_URL             — http://157.151.243.159 (OCI LB)
 *   KAGENT_USER_ID         — admin@kagent.dev
 *   KAGENT_RESUME_AGENT    — commander-agent (or whichever agent handles resumption)
 */

import crypto from "crypto";

const SLACK_SIGNING_SECRET = process.env.SLACK_SIGNING_SECRET;
const KAGENT_URL = process.env.KAGENT_URL;
const KAGENT_RESUME_AGENT = process.env.KAGENT_RESUME_AGENT || "commander-agent";

// ---------------------------------------------------------------------------
// Slack signature verification
// ---------------------------------------------------------------------------

async function verifySlackSignature(req, rawBody) {
  const timestamp = req.headers["x-slack-request-timestamp"];
  const slackSig = req.headers["x-slack-signature"];
  if (!timestamp || !slackSig) return false;

  // Reject replays older than 5 minutes
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp)) > 300) return false;

  const sigBase = `v0:${timestamp}:${rawBody}`;
  const hmac = crypto
    .createHmac("sha256", SLACK_SIGNING_SECRET)
    .update(sigBase)
    .digest("hex");
  const expected = `v0=${hmac}`;

  try {
    return crypto.timingSafeEqual(
      Buffer.from(expected, "utf8"),
      Buffer.from(slackSig, "utf8")
    );
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Resume a kagent agent with the HITL outcome
// ---------------------------------------------------------------------------

async function resumeAgent(requestId, outcome, context) {
  const requestingAgent = context?.requesting_agent || "unknown";
  const resumeMessage =
    `HITL_RESUME\n` +
    `request_id: ${requestId}\n` +
    `outcome: ${outcome}\n` +
    `requesting_agent: ${requestingAgent}\n` +
    `original_context: ${JSON.stringify(context)}`;

  const resp = await fetch(
    `${KAGENT_URL}/api/a2a/kagent/${KAGENT_RESUME_AGENT}/`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Secret": process.env.AUTOBOT_API_SECRET,
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: crypto.randomUUID(),
        method: "message/send",
        params: {
          message: {
            role: "user",
            messageId: crypto.randomUUID(),
            parts: [{ kind: "text", text: resumeMessage }],
          },
        },
      }),
    }
  );

  if (!resp.ok) {
    throw new Error(`kagent ${resp.status}: ${await resp.text()}`);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Merge a GitHub PR (called when HITL approves an R&D PR)
// ---------------------------------------------------------------------------

async function mergeGitHubPR(prNumber, repo) {
  const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
  if (!GITHUB_TOKEN) throw new Error("GITHUB_TOKEN not set in Vercel env");

  const resp = await fetch(
    `https://api.github.com/repos/${repo}/pulls/${prNumber}/merge`,
    {
      method: "PUT",
      headers: {
        "Authorization": `Bearer ${GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ merge_method: "squash" }),
    }
  );

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`GitHub merge failed ${resp.status}: ${body}`);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Replace Slack message buttons with a resolved state
// ---------------------------------------------------------------------------

async function resolveSlackMessage(channelId, messageTs, originalText, outcome, clickedBy) {
  const emoji = { approved: "✅", rejected: "❌", escalated: "⬆️" }[outcome] ?? "❓";
  const ts = Math.floor(Date.now() / 1000);

  await fetch("https://slack.com/api/chat.update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}`,
    },
    body: JSON.stringify({
      channel: channelId,
      ts: messageTs,
      blocks: [
        {
          type: "section",
          text: { type: "mrkdwn", text: originalText },
        },
        {
          type: "context",
          elements: [
            {
              type: "mrkdwn",
              text: `${emoji} *${outcome.toUpperCase()}* by @${clickedBy} at <!date^${ts}^{time_secs}|now>`,
            },
          ],
        },
      ],
    }),
  });
}

// ---------------------------------------------------------------------------
// Timeout escalation — called if no response within severity window
// Severity timeouts: low=30min auto-approve, medium=15min escalate, high=5min reject
// ---------------------------------------------------------------------------

// Note: Vercel functions are stateless — timeouts are best handled by the
// posting side (slack_poster.py). See slack_poster.py for the timeout scheduler.

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  // Read raw body (needed for signature verification)
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const rawBody = Buffer.concat(chunks).toString("utf8");

  if (!(await verifySlackSignature(req, rawBody))) {
    console.error("Slack signature verification failed");
    return res.status(401).json({ error: "Unauthorized" });
  }

  // Slack sends interactions as URL-encoded payload= field
  const params = new URLSearchParams(rawBody);
  const payloadRaw = params.get("payload");
  if (!payloadRaw) return res.status(400).json({ error: "Missing payload" });

  let payload;
  try {
    payload = JSON.parse(payloadRaw);
  } catch {
    return res.status(400).json({ error: "Bad JSON" });
  }

  // Only handle button clicks
  if (payload.type !== "block_actions") {
    return res.status(200).json({ ok: true });
  }

  const action = payload.actions?.[0];
  if (!action) return res.status(200).json({ ok: true });

  const outcome = action.action_id; // "approved" | "rejected" | "escalated"
  let value = {};
  try { value = JSON.parse(action.value || "{}"); } catch { /* ignore */ }

  const { request_id, context } = value;
  const clickedBy = payload.user?.name || "unknown";
  const originalText = payload.message?.blocks?.[0]?.text?.text ?? "HITL Request";

  console.log(`HITL: ${outcome} | request_id=${request_id} | by=${clickedBy}`);

  // Update Slack message to remove buttons and show resolution
  await resolveSlackMessage(
    payload.channel.id,
    payload.message.ts,
    originalText,
    outcome,
    clickedBy
  ).catch((e) => console.error("Failed to update Slack message:", e));

  // If this is a PR approval, merge it on GitHub
  if (outcome === "approved" && value.pr_number && value.repo) {
    try {
      const mergeResult = await mergeGitHubPR(value.pr_number, value.repo);
      console.log(`Merged PR #${value.pr_number}: ${JSON.stringify(mergeResult)}`);

      // Post confirmation to Slack
      await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}`,
        },
        body: JSON.stringify({
          channel: payload.channel.id,
          thread_ts: payload.message.ts,
          text: `✅ PR #${value.pr_number} merged into main via squash merge.`,
        }),
      }).catch(() => {});
    } catch (e) {
      console.error(`Failed to merge PR #${value.pr_number}:`, e);
      await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${process.env.SLACK_BOT_TOKEN}`,
        },
        body: JSON.stringify({
          channel: payload.channel.id,
          thread_ts: payload.message.ts,
          text: `⚠️ PR #${value.pr_number} approval noted but merge failed: ${e.message}`,
        }),
      }).catch(() => {});
    }
  }

  // Resume the agent — log failures but always return 200 to Slack
  // (Slack retries on non-200, which would double-fire the resume)
  await resumeAgent(request_id, outcome, context).catch((e) =>
    console.error("Failed to resume agent:", e)
  );

  return res.status(200).json({ ok: true });
}