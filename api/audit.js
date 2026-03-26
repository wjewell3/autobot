const KAGENT_URL = process.env.KAGENT_URL || "http://157.151.243.159";

export default async function handler(req, res) {
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });

  const cookies = Object.fromEntries(
    (req.headers.cookie || "").split(";").filter(Boolean).map(c => {
      const [k, ...v] = c.trim().split("=");
      return [k, v.join("=")];
    })
  );
  if (cookies["autobot-auth"] !== process.env.AUTOBOT_PASSWORD) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  // Forward query params to audit-api
  const params = new URLSearchParams(req.query).toString();
  const path = req.query.path || "entries";
  const target = `${KAGENT_URL}/audit-api/${path}${params ? "?" + params : ""}`;

  try {
    const response = await fetch(target, {
      headers: {
        "Accept": "application/json",
        "X-API-Secret": process.env.AUTOBOT_API_SECRET,
      },
    });
    const data = await response.json();
    res.status(200).json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
