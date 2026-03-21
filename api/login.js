export default function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();
  try {
    const { password } = JSON.parse(req.body || "{}");
    if (password === process.env.AUTOBOT_PASSWORD) {
      res.setHeader("Set-Cookie", `autobot-auth=${process.env.AUTOBOT_PASSWORD}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000`);
      return res.status(200).json({ ok: true });
    }
  } catch {}
  res.status(401).json({ error: "Invalid password" });
}
