const KAGENT_URL = process.env.KAGENT_URL || "http://157.151.243.159";

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
