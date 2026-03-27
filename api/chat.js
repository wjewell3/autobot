const KAGENT_URL = process.env.KAGENT_URL || "http://157.151.243.159";
const AGENT = "commander-agent";
const NAMESPACE = "kagent";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  // Auth check
  const cookies = Object.fromEntries(
    (req.headers.cookie || "").split(";").filter(Boolean).map(c => {
      const [k, ...v] = c.trim().split("=");
      return [k, v.join("=")];
    })
  );
  if (cookies["autobot-auth"] !== process.env.AUTOBOT_PASSWORD) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const { message, sessionId } = req.body;
  if (!message) return res.status(400).json({ error: "message required" });

  const body = {
    id: crypto.randomUUID(),
    jsonrpc: "2.0",
    method: "message/send",
    params: {
      message: {
        role: "user",
        parts: [{ kind: "text", text: message }],
        messageId: crypto.randomUUID(),
      },
      ...(sessionId ? { sessionId } : {}),
    },
  };

  const TIMEOUT_MS = 55_000; // just under Hobby plan's 60s hard limit
  const timeoutPromise = new Promise((_, reject) =>
    setTimeout(() => reject(new Error("PIPELINE_TIMEOUT")), TIMEOUT_MS)
  );

  try {
    const fetchPromise = fetch(
      `${KAGENT_URL}/api/a2a/${NAMESPACE}/${AGENT}/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Secret": process.env.AUTOBOT_API_SECRET,
        },
        body: JSON.stringify(body),
      }
    );
    const response = await Promise.race([fetchPromise, timeoutPromise]);
    const data = await response.json();
    const result = data?.result;
    const newSessionId = result?.contextId || result?.sessionId || sessionId;
    const history = result?.history || [];
    const agentMessages = history.filter(m => m.role === "agent");
    const lastAgent = agentMessages[agentMessages.length - 1];
    const artifacts = result?.artifacts || [];
    const artifactText = artifacts
      .flatMap(a => a.parts || [])
      .filter(p => p.kind === "text")
      .map(p => p.text)
      .join("\n");
    const msgText = (lastAgent?.parts || [])
      .filter(p => p.kind === "text")
      .map(p => p.text)
      .join("\n");
    const reply = artifactText || msgText || "No response";
    res.status(200).json({ reply, sessionId: newSessionId });
  } catch (err) {
    if (err.message === "PIPELINE_TIMEOUT") {
      // Agent is still running in the cluster — Vercel just couldn't wait.
      // Return a clean JSON response so the UI doesn't blow up.
      return res.status(200).json({
        reply: "⏳ The pipeline is running in the background — this usually takes 2–5 minutes.\n\nWhile you wait:\n• Check **#hitl-approvals** in Slack for any outreach approval requests\n• Watch the **AUDIT FEED** tab for live progress\n• Send another message here to check status",
        sessionId: body.params.sessionId || null,
        pending: true,
      });
    }
    console.error("Chat error:", err.message);
    res.status(500).json({ error: err.message });
  }
}
