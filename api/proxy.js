// Vercel serverless function — proxies requests to kagent API
// bypassing CORS restrictions entirely
const KAGENT_URL = "https://ct0nsvobr7.localto.net";

module.exports = async function handler(req, res) {
  const path = req.url.replace("/api/proxy", "");
  const target = `${KAGENT_URL}${path}`;

  try {
    const response = await fetch(target, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: req.method !== "GET" && req.method !== "HEAD"
        ? JSON.stringify(req.body)
        : undefined,
    });

    const data = await response.json();
    res.status(response.status).json(data);
  } catch (err) {
    console.error("Proxy error:", err.message, "target:", target);
    res.status(500).json({ error: err.message, target });
  }
}