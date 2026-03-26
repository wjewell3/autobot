const KAGENT_URL = "https://ct0nsvobr7.localto.net";

const TESTS = {
  "cso-audit": {
    name: "CSO Security Audit",
    description: "CSO inspects all agents, checks tool assignments, reviews audit log",
    agent: "cso-agent",
    message: "Perform a full security audit now. List all agents, check each agent's tools, review the audit log, and report.",
  },
  "coo-drift": {
    name: "COO Drift Check",
    description: "COO reads audit log, checks for operational drift against pipeline vision",
    agent: "coo-agent",
    message: "Perform an operations check now. Read recent audit entries, check agent activity, flag any drift, and report.",
  },
  "pm-backlog": {
    name: "PM Backlog Check",
    description: "PM reads audit log for task entries and reports current backlog",
    agent: "pm-agent",
    message: "What's in the backlog? Read the audit log and report the current task status.",
  },
  "pm-prospect": {
    name: "PM Prospecting (E2E)",
    description: "Full pipeline: PM triages, creates task, delegates to prospecting-agent, logs results",
    agent: "pm-agent",
    message: "Find plumbing businesses needing websites in Nashville, TN. Check backlog first, create a task, delegate to prospecting-agent, and report results.",
  },
};

export default async function handler(req, res) {
  const cookies = Object.fromEntries(
    (req.headers.cookie || "").split(";").filter(Boolean).map(c => {
      const [k, ...v] = c.trim().split("=");
      return [k, v.join("=")];
    })
  );
  if (cookies["autobot-auth"] !== process.env.AUTOBOT_PASSWORD) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  // GET — list available tests
  if (req.method === "GET") {
    return res.status(200).json({
      tests: Object.entries(TESTS).map(([id, t]) => ({
        id,
        name: t.name,
        description: t.description,
        agent: t.agent,
      })),
    });
  }

  // POST — run a test
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  const { testId } = req.body;
  const test = TESTS[testId];
  if (!test) return res.status(400).json({ error: `Unknown test: ${testId}` });

  // Send via A2A to commander (which routes to the appropriate agent)
  const body = {
    id: crypto.randomUUID(),
    jsonrpc: "2.0",
    method: "message/send",
    params: {
      message: {
        role: "user",
        parts: [{ kind: "text", text: test.message }],
        messageId: crypto.randomUUID(),
      },
    },
  };

  try {
    const response = await fetch(
      `${KAGENT_URL}/api/a2a/kagent/commander-agent/`,
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
    const artifacts = result?.artifacts || [];
    const artifactText = artifacts
      .flatMap(a => a.parts || [])
      .filter(p => p.kind === "text")
      .map(p => p.text)
      .join("\n");
    const history = result?.history || [];
    const agentMessages = history.filter(m => m.role === "agent");
    const lastAgent = agentMessages[agentMessages.length - 1];
    const msgText = (lastAgent?.parts || [])
      .filter(p => p.kind === "text")
      .map(p => p.text)
      .join("\n");
    const reply = artifactText || msgText || "No response";

    res.status(200).json({
      testId,
      name: test.name,
      agent: test.agent,
      result: reply,
      status: reply.toLowerCase().includes("error") ? "warning" : "pass",
    });
  } catch (err) {
    res.status(500).json({
      testId,
      name: test.name,
      agent: test.agent,
      error: err.message,
      status: "fail",
    });
  }
}
