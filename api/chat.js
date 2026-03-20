const KAGENT_URL = "https://ct0nsvobr7.localto.net";
const AGENT = "commander-agent";
const NAMESPACE = "kagent";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

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
      `${KAGENT_URL}/api/a2a/${NAMESPACE}/${AGENT}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "localtonet-skip-warning": "true",
        },
        body: JSON.stringify(body),
      }
    );

    const data = await response.json();
    console.log("A2A response:", JSON.stringify(data).slice(0, 1000));

    // Extract reply from A2A response
    const parts = data?.result?.status?.message?.parts ||
                  data?.result?.message?.parts ||
                  data?.result?.parts || [];

    const reply = parts
      .filter(p => p.kind === "text" || p.text)
      .map(p => p.text)
      .join("\n") || JSON.stringify(data?.result || data?.error || data);

    const newSessionId = data?.result?.sessionId ||
                        data?.result?.contextId ||
                        sessionId;

    res.status(200).json({ reply, sessionId: newSessionId });
  } catch (err) {
    console.error("Chat error:", err.message);
    res.status(500).json({ error: err.message });
  }
}