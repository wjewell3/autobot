import { useState, useEffect, useRef } from "react";

// ── CONFIG ─────────────────────────────────────────────
// Update this to your current trycloudflare URL
// In future this will be stable once you have a domain
const KAGENT_API = "https://permalink-acquisition-collectors-tribes.trycloudflare.com";
const POLL_MS = 3000;
// ───────────────────────────────────────────────────────

const AGENTS = [
  { id: "commander-agent",   label: "Commander",  emoji: "👑", x: 300, y: 40  },
  { id: "number-agent-1",    label: "Agent 1",    emoji: "🎲", x: 100, y: 180 },
  { id: "number-agent-2",    label: "Agent 2",    emoji: "🎲", x: 250, y: 280 },
  { id: "number-agent-3",    label: "Agent 3",    emoji: "🎲", x: 400, y: 180 },
  { id: "sum-agent",         label: "Sum Agent",  emoji: "🧮", x: 300, y: 370 },
  { id: "k8s-agent",         label: "K8s",        emoji: "⚙️", x: 520, y: 40  },
  { id: "helm-agent",        label: "Helm",       emoji: "🪖", x: 520, y: 130 },
  { id: "observability-agent", label: "Observe",  emoji: "📊", x: 520, y: 220 },
];

const EDGES = [
  { from: "commander-agent", to: "number-agent-1" },
  { from: "number-agent-1",  to: "number-agent-2" },
  { from: "number-agent-2",  to: "number-agent-3" },
  { from: "number-agent-3",  to: "sum-agent"      },
  { from: "sum-agent",       to: "commander-agent"},
];

const STATUS_COLOR = {
  idle:    "#334155",
  active:  "#6366f1",
  ready:   "#22c55e",
  error:   "#ef4444",
  unknown: "#64748b",
};

function statusColor(s) {
  if (!s) return STATUS_COLOR.unknown;
  if (s.toLowerCase().includes("ready") || s.toLowerCase().includes("running")) return STATUS_COLOR.ready;
  if (s.toLowerCase().includes("error") || s.toLowerCase().includes("fail"))   return STATUS_COLOR.error;
  if (s.toLowerCase().includes("active") || s.toLowerCase().includes("busy"))  return STATUS_COLOR.active;
  return STATUS_COLOR.unknown;
}

export default function App() {
  const [agents, setAgents] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [log, setLog]     = useState([]);
  const [error, setError] = useState(null);
  const [lastPoll, setLastPoll] = useState(null);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const addLog = (msg, color = "#94a3b8") =>
    setLog(l => [...l.slice(-50), { msg, color, t: new Date().toLocaleTimeString() }]);

  const poll = async () => {
    try {
      const [agentRes, sessionRes] = await Promise.all([
        fetch(`${KAGENT_API}/api/v1/agents/kagent`),
        fetch(`${KAGENT_API}/api/v1/sessions/kagent`),
      ]);
      if (!agentRes.ok) throw new Error(`Agent API ${agentRes.status}`);
      const agentData   = await agentRes.json();
      const sessionData = sessionRes.ok ? await sessionRes.json() : [];
      setAgents(agentData?.agents || agentData || []);
      setSessions(sessionData?.sessions || sessionData || []);
      setError(null);
      setLastPoll(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, []);

  const getAgent = id => agents.find(a => a.name === id || a.metadata?.name === id);
  const getPos   = id => AGENTS.find(a => a.id === id);

  return (
    <div style={{ background: "#0f172a", minHeight: "100vh", color: "#e2e8f0", fontFamily: "monospace", padding: 20 }}>
      <div style={{ textAlign: "center", marginBottom: 16 }}>
        <h2 style={{ color: "#a78bfa", margin: 0 }}>🤖 Agent Army — Live Dashboard</h2>
        <p style={{ color: error ? "#ef4444" : "#64748b", fontSize: 11, margin: "4px 0" }}>
          {error ? `⚠️ ${error}` : `✅ Live · Last poll: ${lastPoll || "..."} · Polling every ${POLL_MS/1000}s`}
        </p>
      </div>

      <div style={{ display: "flex", gap: 16, maxWidth: 1100, margin: "0 auto" }}>
        {/* SVG diagram */}
        <div style={{ background: "#1e293b", borderRadius: 12, padding: 12, flex: "0 0 640px" }}>
          <svg width={640} height={460} viewBox="0 0 640 460">
            {EDGES.map((e, i) => {
              const f = getPos(e.from), t = getPos(e.to);
              if (!f || !t) return null;
              return (
                <line key={i}
                  x1={f.x + 45} y1={f.y + 30}
                  x2={t.x + 45} y2={t.y + 30}
                  stroke="#334155" strokeWidth={1.5}
                />
              );
            })}
            {AGENTS.map(a => {
              const live  = getAgent(a.id);
                  const status = live?.status?.conditions?.[0]?.type || live?.status || null;
              const col   = statusColor(status);
              return (
                <g key={a.id} transform={`translate(${a.x}, ${a.y})`}>
                  <rect width={90} height={60} rx={10}
                    fill="#0f172a" stroke={col} strokeWidth={live ? 2 : 1} />
                  <text x={45} y={20} textAnchor="middle" fontSize={16}>{a.emoji}</text>
                  <text x={45} y={34} textAnchor="middle" fontSize={9} fill="#e2e8f0">{a.label}</text>
                  <text x={45} y={48} textAnchor="middle" fontSize={8} fill={col}>
                    {live ? (status || "ready") : "not deployed"}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        {/* Right panel */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Agent list */}
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 12 }}>
            <div style={{ color: "#64748b", fontSize: 11, marginBottom: 8 }}>
              LIVE AGENTS ({agents.length})
            </div>
            {agents.length === 0 && (
              <div style={{ color: "#334155", fontSize: 11 }}>No agents found</div>
            )}
            {agents.map((a, i) => {
              const name   = a.name || a.metadata?.name || "unknown";
              const status = a.status?.conditions?.[0]?.type || a.status || "unknown";
              return (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 4 }}>
                  <span style={{ color: "#e2e8f0" }}>{name}</span>
                  <span style={{ color: statusColor(status) }}>{status}</span>
                </div>
              );
            })}
          </div>

          {/* Sessions */}
          <div style={{ background: "#1e293b", borderRadius: 12, padding: 12, flex: 1 }}>
            <div style={{ color: "#64748b", fontSize: 11, marginBottom: 8 }}>
              ACTIVE SESSIONS ({sessions.length})
            </div>
            {sessions.length === 0 && (
              <div style={{ color: "#334155", fontSize: 11 }}>No active sessions</div>
            )}
            {sessions.slice(-10).map((s, i) => (
              <div key={i} style={{ fontSize: 10, marginBottom: 4, color: "#94a3b8" }}>
                <span style={{ color: "#6366f1" }}>{s.agent || s.metadata?.name}</span>
                {" · "}{s.status || "active"}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}