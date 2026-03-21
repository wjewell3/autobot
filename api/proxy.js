const KAGENT_URL = "https://ct0nsvobr7.localto.net";

export default async function handler(req, res) {
  const cookies = Object.fromEntries(
    (req.headers.cookie || "").split(";").map(c => c.trim().split("="))
  );
  if (cookies["autobot-auth"] !== process.env.AUTOBOT_PASSWORD) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  const path = req.url.replace("/api/proxy", "") || "/";
  const target = `${KAGENT_URL}${path}`;
  try {
    const response = await fetch(target, {
      method: req.method,
      headers: {
        "Accept": "application/json",
        "localtonet-skip-warning": "true",
        "X-API-Secret": process.env.AUTOBOT_API_SECRET,
      },
    });
    const text = await response.text();
    try { res.status(response.status).json(JSON.parse(text)); }
    catch { res.status(response.status).send(text); }
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
