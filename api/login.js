export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();
  
  let password;
  try {
    // Vercel auto-parses JSON body when Content-Type is application/json
    password = req.body?.password;
  } catch {
    return res.status(400).json({ error: "Invalid request" });
  }

  if (!process.env.AUTOBOT_PASSWORD) {
    return res.status(500).json({ error: "Server misconfigured - AUTOBOT_PASSWORD not set" });
  }

  if (password === process.env.AUTOBOT_PASSWORD) {
    res.setHeader("Set-Cookie", `autobot-auth=${process.env.AUTOBOT_PASSWORD}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000`);
    return res.status(200).json({ ok: true });
  }
  
  return res.status(401).json({ error: "Invalid password" });
}
