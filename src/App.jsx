import { useState, useEffect, useRef } from "react";

const POLL_MS = 3000;

const KNOWN_AGENTS = [
  { id: "commander-agent",  label: "Commander", emoji: "👑", x: 270, y: 40  },
  { id: "number-agent-1",   label: "Agent 1",   emoji: "🎲", x: 80,  y: 180 },
  { id: "number-agent-2",   label: "Agent 2",   emoji: "🎲", x: 220, y: 280 },
  { id: "number-agent-3",   label: "Agent 3",   emoji: "🎲", x: 360, y: 180 },
  { id: "sum-agent",        label: "Sum",       emoji: "🧮", x: 270, y: 370 },
  { id: "k8s-agent",        label: "K8s",       emoji: "⚙️", x: 460, y: 40  },
  { id: "helm-agent",       label: "Helm",      emoji: "🪖", x: 460, y: 130 },
  { id: "observability-agent", label: "Obs",   emoji: "📊", x: 460, y: 220 },
];

const EDGES = [
  { from: "commander-agent", to: "number-agent-1" },
  { from: "number-agent-1",  to: "number-agent-2" },
  { from: "number-agent-2",  to: "number-agent-3" },
  { from: "number-agent-3",  to: "sum-agent"      },
  { from: "sum-agent",       to: "commander-agent"},
];

function statusColor(s) {
  if (!s) return "#334155";
  const l = s.toLowerCase();
  if (l.includes("ready") || l.includes("true") || l.includes("accepted")) return "#22c55e";
  if (l.includes("error") || l.includes("fail") || l.includes("false"))    return "#ef4444";
  if (l.includes("active") || l.includes("busy"))  return "#6366f1";
  return "#64748b";
}

export default function App() {
  const [agents, setAgents]       = useState([]);
  const [error, setError]         = useState(null);
  const [lastPoll, setLastPoll]   = useState(null);
  const [messages, setMessages]   = useState([
    { role: "assistant", text: "👋 Hi! I'm your Commander agent. Tell me about a business opportunity you want to pursue and I'll help create a plan and build an agent army to execute it." }
  ]);
  const [input, setInput]         = useState("");
  const [thinking, setThinking]   = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const chatRef = useRef(null);
  const pollRef = useRef(null);

  // ── POLLING ───────────────────────────────────────────
  const poll = async () => {
    try {
      const res = await fetch(`/api/proxy/apis/kagent.dev/v1alpha1/namespaces/kagent/agents`);
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setAgents(Array.isArray(data?.items) ? data.items : []);
      setError(null);
      setLastPoll(new Date().toLocaleTimeString());
    } catch (e) { setError(e.message); }
  };

  useEffect(() => {
    poll();
    pollRef.current = setInterval(poll, POLL_MS);
    return () => clearInterval(pollRef.current);
  }, []);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  // ── CHAT ──────────────────────────────────────────────
  const send = async () => {
    if (!input.trim() || thinking) return;
    const userMsg = input.trim();
    setInput("");
    setMessages(m => [...m, { role: "user", text: userMsg }]);
    setThinking(true);

    try {
      const body = {
        sessionId,
        message: userMsg,
      };

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();
      if (data.sessionId) setSessionId(data.sessionId);
      setMessages(m => [...m, { role: "assistant", text: data.reply || "..." }]);
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    } finally {
      setThinking(false);
    }
  };

  const onKey = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };

  // ── RENDER ────────────────────────────────────────────
  const getKnown = id => KNOWN_AGENTS.find(a => a.id === id);
  const getLive  = id => agents.find(a => a.metadata?.name === id);

  // Build dynamic agents not in KNOWN_AGENTS
  const dynamicAgents = agents.filter(a => !KNOWN_AGENTS.find(k => k.id === a.metadata?.name));

  return (
    <div style={{ background: "#0f172a", minHeight: "100vh", color: "#e2e8f0", fontFamily: "monospace", padding: 16, boxSizing: "border-box" }}>

      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 12 }}>
        <h2 style={{ color: "#a78bfa", margin: 0, fontSize: 18 }}>🤖 Autobot — Agent Army Command Center</h2>
        <p style={{ color: error ? "#ef4444" : "#22c55e", fontSize: 11, margin: "4px 0" }}>
          {error ? `⚠️ ${error}` : `✅ Live · ${lastPoll || "..."} · ${agents.length} agents`}
        </p>
      </div>

      <div style={{ display: "flex", gap: 12, maxWidth: 1200, margin: "0 auto", height: "calc(100vh - 80px)" }}>

        {/* Left — Diagram + Agent List */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, flex: "0 0 560px" }}>

          {/* Diagram */}
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 10 }}>
            <svg width={540} height={420} viewBox="0 0 540 420">
              {EDGES.map((e, i) => {
                const f = KNOWN_AGENTS.find(a => a.id === e.from);
                const t = KNOWN_AGENTS.find(a => a.id === e.to);
                if (!f || !t) return null;
                const fl = getLive(e.from), tl = getLive(e.to);
                const active = fl && tl;
                return (
                  <line key={i}
                    x1={f.x + 45} y1={f.y + 30}
                    x2={t.x + 45} y2={t.y + 30}
                    stroke={active ? "#6366f1" : "#334155"}
                    strokeWidth={active ? 2 : 1.5}
                    strokeDasharray={active ? "6 3" : "none"}
                  />
                );
              })}
              {KNOWN_AGENTS.map(a => {
                const live = getLive(a.id);
                const status = live?.status?.conditions?.[0]?.type || null;
                const col = live ? statusColor(status) : "#334155";
                return (
                  <g key={a.id} transform={`translate(${a.x}, ${a.y})`}>
                    <rect width={90} height={58} rx={10}
                      fill="#0f172a" stroke={col} strokeWidth={live ? 2 : 1} />
                    <text x={45} y={18} textAnchor="middle" fontSize={15}>{a.emoji}</text>
                    <text x={45} y={32} textAnchor="middle" fontSize={9} fill="#e2e8f0">{a.label}</text>
                    <text x={45} y={46} textAnchor="middle" fontSize={8} fill={col}>
                      {live ? (status || "ready") : "not deployed"}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Agent List */}
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 12, flex: 1, overflowY: "auto" }}>
            <div style={{ color: "#64748b", fontSize: 11, marginBottom: 8 }}>LIVE AGENTS ({agents.length})</div>
            {agents.length === 0 && <div style={{ color: "#334155", fontSize: 11 }}>No agents found</div>}
            {agents.map((a, i) => {
              const name   = a.metadata?.name || "unknown";
              const status = a.status?.conditions?.[0]?.type || "unknown";
              const isNew  = !KNOWN_AGENTS.find(k => k.id === name);
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 5, padding: "4px 6px", borderRadius: 6, background: isNew ? "#1a2744" : "transparent" }}>
                  <span style={{ color: isNew ? "#60a5fa" : "#e2e8f0" }}>
                    {isNew ? "✨ " : ""}{name}
                  </span>
                  <span style={{ color: statusColor(status) }}>{status}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right — Chat */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#1e293b", borderRadius: 12, padding: 12 }}>
          <div style={{ color: "#64748b", fontSize: 11, marginBottom: 8 }}>
            COMMANDER CHAT {sessionId ? `· session: ${sessionId.slice(0, 8)}...` : "· new session"}
          </div>

          {/* Messages */}
          <div ref={chatRef} style={{ flex: 1, overflowY: "auto", marginBottom: 10 }}>
            {messages.map((m, i) => (
              <div key={i} style={{
                marginBottom: 10,
                display: "flex",
                flexDirection: "column",
                alignItems: m.role === "user" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: "85%",
                  background: m.role === "user" ? "#6366f1" : "#0f172a",
                  border: m.role === "assistant" ? "1px solid #334155" : "none",
                  borderRadius: 10,
                  padding: "8px 12px",
                  fontSize: 12,
                  color: "#e2e8f0",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.5,
                }}>
                  {m.text}
                </div>
                <div style={{ fontSize: 9, color: "#475569", marginTop: 2 }}>
                  {m.role === "user" ? "you" : "commander"}
                </div>
              </div>
            ))}
            {thinking && (
              <div style={{ color: "#6366f1", fontSize: 12, marginBottom: 8 }}>
                ⟳ Commander is thinking...
              </div>
            )}
          </div>

          {/* Input */}
          <div style={{ display: "flex", gap: 8 }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Tell commander what you want to build... (Enter to send)"
              style={{
                flex: 1,
                background: "#0f172a",
                border: "1px solid #334155",
                borderRadius: 8,
                color: "#e2e8f0",
                padding: "8px 10px",
                fontSize: 12,
                fontFamily: "monospace",
                resize: "none",
                height: 60,
                outline: "none",
              }}
            />
            <button
              onClick={send}
              disabled={thinking || !input.trim()}
              style={{
                background: thinking || !input.trim() ? "#1e293b" : "#6366f1",
                color: "#fff",
                border: "none",
                borderRadius: 8,
                padding: "0 16px",
                cursor: thinking ? "not-allowed" : "pointer",
                fontFamily: "monospace",
                fontSize: 18,
              }}
            >▶</button>
          </div>
        </div>
      </div>
    </div>
  );
}