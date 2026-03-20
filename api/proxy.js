const KAGENT_URL = "https://ct0nsvobr7.localto.net";

export default async function handler(req, res) {
  const path = req.url.replace("/api/proxy", "") || "/";
  const target = `${KAGENT_URL}${path}`;

  console.log("Proxying to:", target);

  try {
    const response = await fetch(target, {
      method: req.method,
      headers: { "Accept": "application/json" },
    });

    console.log("Response status:", response.status);
    const text = await response.text();

    try {
      const data = JSON.parse(text);
      res.status(response.status).json(data);
    } catch {
      res.status(response.status).send(text);
    }
  } catch (err) {
    console.error("Fetch error:", err.message);
    res.status(500).json({ 
      error: err.message, 
      target,
      type: err.constructor.name 
    });
  }
}