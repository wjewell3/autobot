const KAGENT_URL = "https://ct0nsvobr7.localto.net";
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

  try {
    const response = await fetch(
      `${KAGENT_URL}/api/a2a/${NAMESPACE}/${AGENT}/`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "localtonet-skip-warning": "true",
          "X-API-Secret": process.env.AUTOBOT_API_SECRET,
        },
        body: JSON.stringify(body),
      }
    );
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
    console.error("Chat error:", err.message);
    res.status(500).json({ error: err.message });
  }
}
