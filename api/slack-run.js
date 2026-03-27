/**
 * api/slack-run.js — Slack slash command handler for ad-hoc agent triggers
 *
 * Usage in Slack:
 *   /run pipeline         — PM full pipeline (prospect → site → outreach)
 *   /run rd               — R&D evolution cycle
 *   /run northstar        — North Star trajectory assessment
 *   /run cso              — CSO security audit
 *   /run coo              — COO status check
 *   /run cfo              — CFO resource check
 *   /run <free text>      — Send free-text message directly to commander
 *
 * Env vars needed in Vercel:
 *   SLACK_SIGNING_SECRET  — from Slack app settings > Basic Information
 *   SLACK_BOT_TOKEN       — xoxb-... for posting follow-up messages
 *   KAGENT_URL            — http://157.151.243.159
 *   AUTOBOT_API_SECRET    — X-API-Secret for nginx-cors
 */

import crypto from "crypto";

// Disable Vercel's automatic body parsing so we can read the raw body
// for Slack signature verification (requires the exact raw bytes).
export const config = { api: { bodyParser: false } };

const SLACK_SIGNING_SECRET = process.env.SLACK_SIGNING_SECRET;
const KAGENT_URL = process.env.KAGENT_URL;
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN;

// ---------------------------------------------------------------------------
// Known named tasks → (agent, prompt)
// ---------------------------------------------------------------------------

const KNOWN_TASKS = {
  pipeline: {
    agent: "commander-agent",
    prompt:
      "PIPELINE CYCLE (ad-hoc): Route to PM. Ask PM to run the full business pipeline: " +
      "1) Check the backlog for any incomplete tasks (businesses found but no site yet, " +
      "or sites built but no outreach yet). Complete those first. " +
      "2) If the backlog is clear, find 3-5 businesses needing websites in Nashville, TN — " +
      "service trades (plumbing, HVAC, electricians, landscaping). " +
      "3) For each business found, delegate to site-builder-agent to create a demo GitHub Pages site. " +
      "4) For each site built, delegate to outreach-agent to request HITL approval and send outreach. " +
      "5) Write audit entries for each stage. Report a summary of what was done.",
  },
  rd: {
    agent: "rd-agent",
    prompt:
      "Run evolution cycle: inventory all agents, research best practices for the weakest agents, " +
      "and propose system message improvements via GitHub PRs. " +
      "Check your memory for previous cycles to avoid repeating proposals.",
  },
  northstar: {
    agent: "north-star-agent",
    prompt:
      "Run trajectory assessment cycle. Compare current system state against the project vision. " +
      "Score each dimension, identify trends, flag drift, and post your report to Slack. " +
      "If any dimension scores 2 or below, create a gap-fixing PR.",
  },
  cso: {
    agent: "commander-agent",
    prompt:
      "SECURITY AUDIT REQUEST (ad-hoc): Route to CSO. Ask CSO to: " +
      "1) List all agents and their current tools. " +
      "2) Check for any agent with gmail_send_email (forbidden). " +
      "3) Check for agents with tools not in the capability registry. " +
      "4) Write an audit entry summarizing findings. Report the results back.",
  },
  coo: {
    agent: "commander-agent",
    prompt:
      "OPERATIONS CHECK (ad-hoc): Route to COO. Ask COO to: " +
      "1) Read the last 50 audit entries. " +
      "2) Check for any agent errors or repeated failures. " +
      "3) Check for any agents that haven't been active recently. " +
      "4) Post a brief status summary to Slack. Report the results back.",
  },
  cfo: {
    agent: "commander-agent",
    prompt:
      "RESOURCE CHECK (ad-hoc): Route to CFO. Ask CFO to: " +
      "1) Check current token usage and budget burn rate across all agents. " +
      "2) Check cluster resource utilization across all pods in kagent namespace. " +
      "3) Check action budget status — any agents near their limits? " +
      "4) Post a brief resource summary to Slack and flag anything requiring attention. Report back.",
  },
  prospect: {
    agent: "commander-agent",
    prompt:
      "PROSPECTING TASK (ad-hoc): Route to PM. Ask PM to find 5 businesses needing websites " +
      "in Nashville, TN — service trades (plumbing, HVAC, electricians, landscapers). " +
      "Delegate to prospecting-agent. Write audit entries. Report the results back.",
  },
  status: {
    agent: "commander-agent",
    prompt:
      "STATUS CHECK (ad-hoc): Give me a quick status of the agent org. " +
      "Route to COO for the last 20 audit entries and report back what's been happening.",
  },
};

// ---------------------------------------------------------------------------
// Slack signature verification
// ---------------------------------------------------------------------------

function verifySlackSignature(rawBody, timestamp, slackSig) {
  if (!timestamp || !slackSig) return false;
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
// Parse URL-encoded Slack slash command body
// ---------------------------------------------------------------------------

function parseSlackBody(raw) {
  return Object.fromEntries(
    raw
      .split("&")
      .map((pair) => pair.split("=").map(decodeURIComponent))
  );
}

// ---------------------------------------------------------------------------
// Fire A2A request (fire-and-forget — don't await full response)
// ---------------------------------------------------------------------------

async function triggerAgent(agent, prompt, responseUrl) {
  const namespace = "kagent";
  try {
    const resp = await fetch(`${KAGENT_URL}/api/a2a/${namespace}/${agent}/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Secret": process.env.AUTOBOT_API_SECRET,
        "localtonet-skip-warning": "true",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: crypto.randomUUID(),
        method: "message/send",
        params: {
          message: {
            role: "user",
            messageId: crypto.randomUUID(),
            parts: [{ kind: "text", text: prompt }],
          },
        },
      }),
      // Give it up to 9 minutes — CronJob tasks can run long
      signal: AbortSignal.timeout(540_000),
    });

    const data = await resp.json();
    const result = data?.result;
    const history = result?.history || [];
    const agentMessages = history.filter((m) => m.role === "agent");
    const last = agentMessages[agentMessages.length - 1];
    const artifacts = result?.artifacts || [];
    const artifactText = artifacts
      .flatMap((a) => a.parts || [])
      .filter((p) => p.kind === "text")
      .map((p) => p.text)
      .join("\n");
    const msgText = (last?.parts || [])
      .filter((p) => p.kind === "text")
      .map((p) => p.text)
      .join("\n");
    const reply = artifactText || msgText || "✅ Task completed (no text output).";

    // Post result back to Slack via response_url
    await fetch(responseUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        response_type: "in_channel",
        text: `✅ *${agent}* finished:\n\`\`\`\n${reply.slice(0, 2800)}\n\`\`\``,
      }),
    });
  } catch (err) {
    await fetch(responseUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        response_type: "in_channel",
        text: `❌ *${agent}* failed: ${err.message}`,
      }),
    }).catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  // Read raw body for signature verification
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  const rawBody = Buffer.concat(chunks).toString("utf8");

  const valid = verifySlackSignature(
    rawBody,
    req.headers["x-slack-request-timestamp"],
    req.headers["x-slack-signature"]
  );
  if (!valid) {
    return res.status(401).json({ error: "Invalid Slack signature" });
  }

  const params = parseSlackBody(rawBody);
  const text = (params.text || "").trim().toLowerCase();
  const responseUrl = params.response_url;
  const userName = params.user_name || "unknown";

  if (!text) {
    return res.status(200).json({
      response_type: "ephemeral",
      text:
        "Usage: `/run <task>`\n\nAvailable tasks:\n" +
        "• `pipeline` — full prospect → site → outreach cycle\n" +
        "• `rd` — R&D evolution cycle (research + PRs)\n" +
        "• `northstar` — trajectory assessment\n" +
        "• `cso` — security audit\n" +
        "• `cfo` — resource / budget check\n" +
        "• `coo` — ops status check\n" +
        "• `prospect` — prospecting only\n" +
        "• `status` — quick org status\n" +
        "• `<anything else>` — sent as free text to commander",
    });
  }

  const task = KNOWN_TASKS[text];
  const agent = task?.agent || "commander-agent";
  const prompt = task?.prompt || text; // free-text falls through to commander

  // Acknowledge immediately (Slack requires < 3s)
  res.status(200).json({
    response_type: "in_channel",
    text: `⚙️ *@${userName}* triggered \`/run ${text}\` → firing *${agent}*...`,
  });

  // Fire the agent asynchronously — don't block the response
  triggerAgent(agent, prompt, responseUrl).catch(() => {});
}
