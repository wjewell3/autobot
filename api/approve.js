const LOCALTONET = "https://ct0nsvobr7.localto.net";
const SECRET = process.env.AUTOBOT_API_SECRET;

export default async function handler(req, res) {
  const { token, action, business, repo, html } = req.query;

  if (!token) return res.status(400).send("Missing token");

  // Check approval server
  try {
    const statusRes = await fetch(
      `${LOCALTONET}/approval/status?token=${token}`,
      { headers: { "X-API-Secret": SECRET, "localtonet-skip-warning": "true" } }
    );
    const statusData = await statusRes.json();
    if (statusData.status === "APPROVED" || statusData.status === "REJECTED") {
      return res.status(200).send(renderPage(statusData.status, business));
    }
  } catch (e) {
    console.error("Status check failed:", e.message);
  }

  // Record decision on approval server
  try {
    await fetch(
      `${LOCALTONET}/approval/respond?token=${token}&action=${action}`,
      { headers: { "localtonet-skip-warning": "true" } }
    );
  } catch (e) {
    console.error("Respond failed:", e.message);
  }

  const approved = action === "yes";

  if (approved) {
    // Trigger Phase B via kagent A2A
    try {
      const sessionRes = await fetch(`${LOCALTONET}/api/sessions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "localtonet-skip-warning": "true",
          "X-API-Secret": SECRET,
        },
        body: JSON.stringify({
          agent_ref: { name: "commander-agent", namespace: "kagent" },
          user_id: "admin@kagent.dev",
        }),
      });
      const sessionData = await sessionRes.json();
      const sid = sessionData.id || sessionData.session_id || sessionData.sessionId;

      const prompt = `APPROVAL CONFIRMED for business: ${business}.
Repo name: ${repo}.
The website HTML has already been built. Now complete Phase B:
1. Use create_repo to create GitHub repo named "${repo}" if it doesn't exist
2. Use push_file to push the HTML as index.html to that repo
3. Use enable_pages to turn on GitHub Pages
4. Get the live URL with get_pages_url
5. Use send_email to send an email to jewell.will@gmail.com written AS IF you are the owner of "${business}" who just discovered someone built them a free website. Make it excited and personal. Include the live URL. Subject: "Someone built us a website??"
Report each step as you complete it.`;

      await fetch(`${LOCALTONET}/api/a2a/kagent/commander-agent/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "localtonet-skip-warning": "true",
          "X-API-Secret": SECRET,
        },
        body: JSON.stringify({
          id: crypto.randomUUID(),
          jsonrpc: "2.0",
          method: "message/send",
          params: {
            message: {
              role: "user",
              parts: [{ kind: "text", text: prompt }],
              messageId: crypto.randomUUID(),
            },
            sessionId: sid,
          },
        }),
      });

      console.log(`[approve] APPROVED business=${business} repo=${repo} triggered Phase B`);
    } catch (e) {
      console.error("Phase B trigger failed:", e.message);
    }
  }

  return res.status(200).send(renderPage(approved ? "APPROVED" : "REJECTED", business));
}

function renderPage(status, business) {
  const approved = status === "APPROVED";
  const color = approved ? "#22c55e" : "#ef4444";
  const emoji = approved ? "✅" : "❌";
  const message = approved
    ? `Building and deploying the website for ${business || "the business"}...`
    : `Pipeline stopped for ${business || "the business"}.`;
  return `
<html>
<head>
  <title>Autobot</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="font-family: Arial, sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; background: #0f172a;">
  <div style="text-align: center; color: white; padding: 40px;">
    <div style="font-size: 80px;">${emoji}</div>
    <h1 style="color: ${color}; font-size: 32px; margin: 20px 0;">${status}</h1>
    <p style="color: #94a3b8; font-size: 16px; max-width: 400px;">${message}</p>
    ${approved ? `<p style="color: #475569; font-size: 13px; margin-top: 30px;">Check your email for the final result. You can close this tab.</p>` : `<p style="color: #475569; font-size: 13px; margin-top: 30px;">You can close this tab.</p>`}
  </div>
</body>
</html>`;
}
