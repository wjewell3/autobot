import { useState, useEffect, useRef } from "react";

function useIsMobile() {
  const [mobile, setMobile] = useState(() => typeof window !== "undefined" && window.innerWidth < 768);
  useEffect(() => {
    const h = () => setMobile(window.innerWidth < 768);
    window.addEventListener("resize", h);
    return () => window.removeEventListener("resize", h);
  }, []);
  return mobile;
}

// ── Shared Styles & Helpers ─────────────────────────────

const FONT = "'JetBrains Mono', 'Fira Code', monospace";
const BG = "#080f1a";
const PANEL = "#0a1628";
const BORDER = "#1e293b";
const MUTED = "#334155";
const TEXT = "#e2e8f0";
const ACCENT = "#a78bfa";
const GREEN = "#22c55e";
const RED = "#ef4444";
const YELLOW = "#facc15";

const GLOBAL_CSS = `
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');
*, *::before, *::after { box-sizing: border-box; }
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #0f172a; }
::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }
textarea:focus, input:focus { outline: none; }
.msg-in { animation: fadeUp 0.2s ease; }
@keyframes fadeUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
.blink { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }
.scan-line {
  position: absolute; inset: 0; pointer-events: none; z-index: 0;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,180,0.015) 2px, rgba(0,255,180,0.015) 4px);
}
.fade-in { animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@media (max-width: 767px) {
  body { -webkit-text-size-adjust: 100%; }
  input, textarea, select { font-size: 16px !important; }
}
`;

function getAgentColor(name) {
  if (name === "commander-agent") return ACCENT;
  if (name.includes("ceo")) return "#facc15";
  if (name.includes("coo")) return "#fb923c";
  if (name.includes("cso")) return "#f87171";
  if (name.includes("pm-")) return "#34d399";
  if (name.includes("prospect")) return "#38bdf8";
  if (name.includes("site-builder")) return "#22d3ee";
  if (name.includes("number")) return "#38bdf8";
  if (name.includes("sum")) return "#34d399";
  const hash = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  const colors = ["#38bdf8", "#34d399", "#fb923c", "#f472b6", "#facc15", "#a78bfa", "#f87171"];
  return colors[hash % colors.length];
}

function getAgentEmoji(name) {
  if (name === "commander-agent") return "⬡";
  if (name.includes("ceo")) return "♔";
  if (name.includes("coo")) return "◎";
  if (name.includes("cso")) return "⛊";
  if (name.includes("pm-")) return "▦";
  if (name.includes("prospect")) return "⌕";
  if (name.includes("site-builder")) return "⚑";
  if (name.includes("number")) return "◈";
  if (name.includes("sum")) return "∑";
  return "◆";
}

function Panel({ children, style = {} }) {
  return (
    <div style={{
      background: PANEL,
      border: `1px solid ${BORDER}`,
      borderRadius: 8,
      padding: 12,
      ...style,
    }}>
      {children}
    </div>
  );
}

function Badge({ color, children }) {
  return (
    <span style={{
      background: `${color}22`,
      color,
      border: `1px solid ${color}44`,
      borderRadius: 4,
      padding: "2px 8px",
      fontSize: 9,
      fontWeight: 600,
      letterSpacing: 1,
    }}>
      {children}
    </span>
  );
}

// ── Login ────────────────────────────────────────────────

function LoginScreen({ onLogin }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!password.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (res.ok) onLogin();
      else setError("Invalid password");
    } catch { setError("Connection error"); }
    finally { setLoading(false); }
  };

  return (
    <div style={{ background: BG, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT }}>
      <style>{GLOBAL_CSS}</style>
      <div style={{ textAlign: "center", width: "min(320px, calc(100vw - 32px))" }}>
        <div style={{ color: ACCENT, fontSize: 28, fontWeight: 600, letterSpacing: 4, marginBottom: 8 }}>AUTOBOT</div>
        <div style={{ color: MUTED, fontSize: 11, letterSpacing: 2, marginBottom: 40 }}>COMMAND CENTER</div>
        <Panel>
          <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1, marginBottom: 12, textAlign: "left" }}>ACCESS CODE</div>
          <input
            type="password" value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => e.key === "Enter" && submit()}
            autoFocus placeholder="enter password"
            style={{
              width: "100%", background: "#0f172a", border: `1px solid ${error ? RED : BORDER}`,
              borderRadius: 6, color: TEXT, padding: "10px 12px", fontSize: 12,
              fontFamily: "inherit", boxSizing: "border-box", marginBottom: 12,
            }}
          />
          {error && <div style={{ color: RED, fontSize: 10, marginBottom: 10, textAlign: "left" }}>{error}</div>}
          <button onClick={submit} disabled={loading || !password.trim()} style={{
            width: "100%", background: loading ? "transparent" : "rgba(99,102,241,0.2)",
            color: loading ? MUTED : ACCENT, border: `1px solid ${loading ? BORDER : "rgba(99,102,241,0.4)"}`,
            borderRadius: 6, padding: "10px 0", cursor: loading ? "not-allowed" : "pointer",
            fontFamily: "inherit", fontSize: 12, letterSpacing: 1,
          }}>
            {loading ? "AUTHENTICATING..." : "ENTER ▶"}
          </button>
        </Panel>
      </div>
    </div>
  );
}

// ── Agent Graph (SVG) ────────────────────────────────────

const RING_RADIUS = 180;
const SVG_W = 540;
const SVG_H = 460;
const CX = SVG_W / 2;
const CY = SVG_H / 2 - 10;

function computeLayout(agents) {
  const nodes = {};
  if (agents.find(a => a.metadata?.name === "commander-agent")) {
    nodes["commander-agent"] = { x: 0, y: 0 };
  }
  const others = agents.filter(a => a.metadata?.name !== "commander-agent");
  const count = others.length;
  others.forEach((a, i) => {
    const angle = (i / Math.max(count, 1)) * 2 * Math.PI - Math.PI / 2;
    const r = count <= 4 ? RING_RADIUS : count <= 8 ? RING_RADIUS * 1.1 : RING_RADIUS * 1.25;
    nodes[a.metadata.name] = { x: Math.cos(angle) * r, y: Math.sin(angle) * r };
  });
  return nodes;
}

function AgentNode({ agent, pos, selected, onClick, sessionData }) {
  const name = agent.metadata?.name || "unknown";
  const conditions = agent.status?.conditions || [];
  const isReady = conditions.some(c => c.type === "Ready" && c.status === "True");
  const isAccepted = conditions.some(c => c.type === "Accepted" && c.status === "True");
  const isCommander = name === "commander-agent";
  const color = getAgentColor(name);
  const emoji = getAgentEmoji(name);
  const taskCount = sessionData?.taskCount || 0;
  const isActive = sessionData?.isActive;
  const size = isCommander ? 54 : 42;

  return (
    <g onClick={() => onClick(name)} style={{ cursor: "pointer" }} transform={`translate(${pos.x}, ${pos.y})`}>
      {isActive && (
        <circle r={size / 2 + 10} fill="none" stroke={color} strokeWidth="1" opacity="0.3">
          <animate attributeName="r" values={`${size/2+6};${size/2+16};${size/2+6}`} dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
        </circle>
      )}
      <circle r={size/2} fill="#0f172a" stroke={selected ? "#fff" : color}
        strokeWidth={selected ? 2 : isCommander ? 1.5 : 1} opacity={isReady || isAccepted ? 1 : 0.4} />
      <text textAnchor="middle" dominantBaseline="central" fontSize={isCommander ? 20 : 16}
        fill={color} y={-2} style={{ fontFamily: "monospace", userSelect: "none" }}>{emoji}</text>
      {taskCount > 0 && (
        <g transform={`translate(${size/2-6}, ${-size/2+6})`}>
          <circle r={8} fill={color} />
          <text textAnchor="middle" dominantBaseline="central" fontSize={8} fill="#0f172a" fontWeight="600">
            {taskCount > 99 ? "99+" : taskCount}
          </text>
        </g>
      )}
      <text y={size/2+14} textAnchor="middle" fontSize={9} fill={selected ? "#fff" : "#94a3b8"}
        style={{ fontFamily: "monospace", userSelect: "none" }}>{name.replace("-agent", "").slice(0, 14)}</text>
    </g>
  );
}

// ── Tab: Agents (Graph + Chat) ───────────────────────────

function AgentsTab({ agents, layout, sessionMap, setSessionMap, selected, setSelected }) {
  const [messages, setMessages] = useState([
    { role: "assistant", text: "Hi! I'm your Commander. Tell me what you'd like to do and I'll route it to the right agent." }
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [activityLog, setActivityLog] = useState([]);
  const [showGraph, setShowGraph] = useState(false);
  const isMobile = useIsMobile();
  const chatRef = useRef(null);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages, thinking]);

  const send = async () => {
    if (!input.trim() || thinking) return;
    const userMsg = input.trim();
    setInput("");
    setMessages(m => [...m, { role: "user", text: userMsg }]);
    setThinking(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg, sessionId }),
      });
      const data = await res.json();
      if (data.sessionId) setSessionId(data.sessionId);
      const reply = data.reply || data.error || "no response";
      setMessages(m => [...m, { role: "assistant", text: reply }]);
      setActivityLog(l => [
        { time: new Date().toLocaleTimeString(), agent: "commander-agent", text: reply.slice(0, 80) },
        ...l.slice(0, 19)
      ]);
      setSessionMap(prev => ({
        ...prev,
        "commander-agent": {
          ...prev["commander-agent"],
          lastOutput: reply.slice(0, 20),
          taskCount: (prev["commander-agent"]?.taskCount || 0) + 1,
          isActive: true,
        }
      }));
      setTimeout(() => {
        setSessionMap(prev => ({
          ...prev,
          "commander-agent": { ...prev["commander-agent"], isActive: false }
        }));
      }, 5000);
    } catch (e) {
      setMessages(m => [...m, { role: "assistant", text: `Error: ${e.message}` }]);
    } finally { setThinking(false); }
  };

  const selectedAgent = selected ? agents.find(a => a.metadata?.name === selected) : null;

  return (
    <div style={{ display: "flex", flexDirection: isMobile ? "column" : "row", gap: 10, height: "100%" }} className="fade-in">
      {/* Mobile graph toggle */}
      {isMobile && (
        <button onClick={() => setShowGraph(g => !g)} style={{
          background: "transparent", color: showGraph ? ACCENT : MUTED,
          border: `1px solid ${showGraph ? "rgba(99,102,241,0.3)" : BORDER}`,
          borderRadius: 6, padding: "8px 12px", cursor: "pointer",
          fontFamily: FONT, fontSize: 11, letterSpacing: 1, textAlign: "left",
        }}>
          {showGraph ? "▴ HIDE GRAPH" : "▾ SHOW AGENT GRAPH"}
        </button>
      )}

      {/* LEFT: Graph + Detail */}
      {(!isMobile || showGraph) && (
      <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: isMobile ? "none" : "0 0 560px" }}>
        {/* Graph */}
        <div style={{ background: PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, position: "relative", overflow: isMobile ? "auto" : "hidden" }}>
          <div className="scan-line" />
          <svg width={SVG_W} height={SVG_H} style={{ display: "block", position: "relative", zIndex: 1 }}>
            {Array.from({ length: 12 }).map((_, row) =>
              Array.from({ length: 15 }).map((_, col) => (
                <circle key={`${row}-${col}`} cx={col*38+10} cy={row*38+10} r={0.8} fill={BORDER} />
              ))
            )}
            {agents.filter(a => a.metadata?.name !== "commander-agent").map(a => {
              const name = a.metadata?.name;
              const pos = layout[name];
              const cmdPos = layout["commander-agent"];
              if (!pos || !cmdPos) return null;
              return (
                <line key={name} x1={CX+cmdPos.x} y1={CY+cmdPos.y} x2={CX+pos.x} y2={CY+pos.y}
                  stroke={getAgentColor(name)} strokeWidth={0.5} opacity={0.2} strokeDasharray="4 4" />
              );
            })}
            {agents.map(a => {
              const name = a.metadata?.name;
              const pos = layout[name];
              if (!pos) return null;
              return (
                <AgentNode key={name} agent={a} pos={{ x: CX+pos.x, y: CY+pos.y }}
                  selected={selected === name} onClick={setSelected} sessionData={sessionMap[name]} />
              );
            })}
          </svg>
        </div>

        {/* Detail Panel */}
        <Panel style={{ flex: 1, overflowY: "auto", fontSize: 11 }}>
          {selected && selectedAgent ? (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <span style={{ color: getAgentColor(selected), fontSize: 16 }}>{getAgentEmoji(selected)}</span>
                <span style={{ color: TEXT, fontWeight: 600, fontSize: 12 }}>{selected}</span>
                <span onClick={() => setSelected(null)} style={{ marginLeft: "auto", color: MUTED, cursor: "pointer", fontSize: 10 }}>✕ close</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                {[
                  ["TYPE", selectedAgent.spec?.type || "—"],
                  ["MODEL", selectedAgent.spec?.declarative?.modelConfig || "—"],
                  ["TASKS", sessionMap[selected]?.taskCount || 0],
                  ["STATUS", selectedAgent.status?.conditions?.find(c => c.status === "True")?.type || "unknown"],
                ].map(([k, v]) => (
                  <div key={k} style={{ background: "#0f172a", borderRadius: 6, padding: "6px 10px" }}>
                    <div style={{ color: MUTED, fontSize: 9, marginBottom: 2 }}>{k}</div>
                    <div style={{ color: getAgentColor(selected), fontSize: 11 }}>{String(v)}</div>
                  </div>
                ))}
              </div>
              {selectedAgent.spec?.declarative?.systemMessage && (
                <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 10px" }}>
                  <div style={{ color: MUTED, fontSize: 9, marginBottom: 4 }}>SYSTEM MESSAGE</div>
                  <div style={{ color: "#64748b", fontSize: 10, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                    {selectedAgent.spec.declarative.systemMessage.slice(0, 500)}
                    {selectedAgent.spec.declarative.systemMessage.length > 500 ? "..." : ""}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <div style={{ color: MUTED, fontSize: 10, marginBottom: 8, letterSpacing: 1 }}>ACTIVITY LOG</div>
              {activityLog.length === 0 ? (
                <div style={{ color: BORDER, fontSize: 11 }}>No activity yet — send a message to commander</div>
              ) : activityLog.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "flex-start" }}>
                  <span style={{ color: MUTED, whiteSpace: "nowrap", fontSize: 9, paddingTop: 1 }}>{e.time}</span>
                  <span style={{ color: getAgentColor(e.agent), fontSize: 9, whiteSpace: "nowrap" }}>{e.agent.replace("-agent", "")}</span>
                  <span style={{ color: "#64748b", fontSize: 10, lineHeight: 1.4 }}>{e.text}</span>
                </div>
              ))}
            </>
          )}
        </Panel>
      </div>
      )} {/* end mobile conditional graph */}

      {/* RIGHT: Chat */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        background: PANEL, border: `1px solid ${BORDER}`, borderRadius: 8,
        padding: 12, minWidth: 0, position: "relative", overflow: "hidden",
        minHeight: isMobile ? 0 : undefined,
      }}>
        <div className="scan-line" />
        <div style={{ color: MUTED, fontSize: 10, marginBottom: 10, letterSpacing: 1, position: "relative", zIndex: 1 }}>
          COMMANDER CHAT {sessionId ? `· ${sessionId.slice(0, 8)}...` : "· new session"}
        </div>
        <div ref={chatRef} style={{ flex: 1, overflowY: "auto", marginBottom: 10, position: "relative", zIndex: 1 }}>
          {messages.map((m, i) => (
            <div key={i} className="msg-in" style={{
              marginBottom: 12, display: "flex", flexDirection: "column",
              alignItems: m.role === "user" ? "flex-end" : "flex-start",
            }}>
              <div style={{ fontSize: 8, color: MUTED, marginBottom: 3, letterSpacing: 1 }}>
                {m.role === "user" ? "YOU" : "COMMANDER"}
              </div>
              <div style={{
                maxWidth: "88%",
                background: m.role === "user" ? "rgba(99,102,241,0.15)" : "rgba(15,23,42,0.8)",
                border: `1px solid ${m.role === "user" ? "rgba(99,102,241,0.4)" : BORDER}`,
                borderRadius: m.role === "user" ? "10px 10px 2px 10px" : "10px 10px 10px 2px",
                padding: "8px 12px", fontSize: isMobile ? 15 : 11,
                color: m.role === "user" ? "#c7d2fe" : "#94a3b8",
                whiteSpace: "pre-wrap", lineHeight: 1.6,
              }}>
                {m.text}
              </div>
            </div>
          ))}
          {thinking && (
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontSize: 8, color: MUTED, letterSpacing: 1 }}>COMMANDER</div>
              <div style={{ color: "#6366f1", fontSize: 11 }}><span className="blink">block</span></div>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, position: "relative", zIndex: 1 }}>
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="send orders to commander..."
            style={{
              flex: 1, background: "#0f172a", border: `1px solid ${BORDER}`, borderRadius: 6,
              color: TEXT, padding: "10px 12px", fontSize: 16, fontFamily: "inherit",
              resize: "none", height: isMobile ? 72 : 54,
            }}
          />
          <button onClick={send} disabled={thinking || !input.trim()} style={{
            background: thinking || !input.trim() ? "transparent" : "rgba(99,102,241,0.2)",
            color: thinking || !input.trim() ? BORDER : ACCENT,
            border: `1px solid ${thinking || !input.trim() ? BORDER : "rgba(99,102,241,0.4)"}`,
            borderRadius: 6, padding: isMobile ? "0 20px" : "0 16px", cursor: thinking ? "not-allowed" : "pointer",
            fontFamily: "inherit", fontSize: isMobile ? 20 : 16, transition: "all 0.15s",
            minWidth: 52,
          }}>▶</button>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Audit Feed ──────────────────────────────────────

function AuditTab() {
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ agent: "", type: "" });
  const [autoRefresh, setAutoRefresh] = useState(true);
  const isMobile = useIsMobile();

  const fetchEntries = async () => {
    try {
      const params = new URLSearchParams({ path: "entries", count: "100" });
      if (filter.agent) params.set("agent", filter.agent);
      if (filter.type) params.set("type", filter.type);
      const res = await fetch(`/api/audit?${params}`);
      if (res.ok) {
        const data = await res.json();
        setEntries(data.entries || []);
      }
    } catch {}
    setLoading(false);
  };

  const fetchStats = async () => {
    try {
      const res = await fetch("/api/audit?path=stats");
      if (res.ok) setStats(await res.json());
    } catch {}
  };

  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [filter.agent, filter.type]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => { fetchEntries(); fetchStats(); }, 5000);
    return () => clearInterval(t);
  }, [autoRefresh, filter.agent, filter.type]);

  const eventColor = (type) => {
    if (type === "AGENT_ACTION") return "#34d399";
    if (type === "ADDED") return GREEN;
    if (type === "MODIFIED") return YELLOW;
    if (type === "DELETED") return RED;
    return "#94a3b8";
  };

  const severityColor = (s) => {
    if (s === "error" || s === "critical") return RED;
    if (s === "warning") return YELLOW;
    return "#64748b";
  };

  const allAgents = stats ? Object.keys(stats.agents || {}).sort() : [];
  const allTypes = stats ? Object.keys(stats.event_types || {}).sort() : [];

  return (
    <div style={{ display: "flex", flexDirection: isMobile ? "column" : "row", gap: 10, height: "100%" }} className="fade-in">
      {/* LEFT: Stats + Filters */}
      <div style={{ flex: isMobile ? "none" : "0 0 280px", display: "flex", flexDirection: isMobile ? "row" : "column", flexWrap: "wrap", gap: 10 }}>
        <Panel>
          <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1, marginBottom: 10 }}>AUDIT STATS</div>
          {stats ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 10px" }}>
                  <div style={{ color: MUTED, fontSize: 9 }}>TOTAL</div>
                  <div style={{ color: ACCENT, fontSize: 18, fontWeight: 600 }}>{stats.total_entries}</div>
                </div>
                <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 10px" }}>
                  <div style={{ color: MUTED, fontSize: 9 }}>AGENTS</div>
                  <div style={{ color: "#34d399", fontSize: 18, fontWeight: 600 }}>{Object.keys(stats.agents || {}).length}</div>
                </div>
              </div>
              <div style={{ color: MUTED, fontSize: 9, marginBottom: 6 }}>BY EVENT TYPE</div>
              {Object.entries(stats.event_types || {}).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                <div key={type} style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 10 }}>
                  <span style={{ color: eventColor(type) }}>{type}</span>
                  <span style={{ color: "#64748b" }}>{count}</span>
                </div>
              ))}
              <div style={{ color: MUTED, fontSize: 9, marginBottom: 6, marginTop: 10 }}>BY AGENT (top 10)</div>
              {Object.entries(stats.agents || {}).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([agent, count]) => (
                <div key={agent} style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 10 }}>
                  <span style={{ color: getAgentColor(agent + "-agent"), cursor: "pointer" }}
                    onClick={() => setFilter(f => ({ ...f, agent }))}>{agent.replace("_", "-")}</span>
                  <span style={{ color: "#64748b" }}>{count}</span>
                </div>
              ))}
            </>
          ) : (
            <div style={{ color: MUTED, fontSize: 11 }}>Loading...</div>
          )}
        </Panel>

        <Panel>
          <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1, marginBottom: 10 }}>FILTERS</div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: MUTED, fontSize: 9, marginBottom: 4 }}>AGENT</div>
            <select value={filter.agent} onChange={e => setFilter(f => ({ ...f, agent: e.target.value }))}
              style={{
                width: "100%", background: "#0f172a", color: TEXT, border: `1px solid ${BORDER}`,
                borderRadius: 4, padding: "4px 8px", fontSize: 10, fontFamily: FONT,
              }}>
              <option value="">All agents</option>
              {allAgents.map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div style={{ marginBottom: 8 }}>
            <div style={{ color: MUTED, fontSize: 9, marginBottom: 4 }}>EVENT TYPE</div>
            <select value={filter.type} onChange={e => setFilter(f => ({ ...f, type: e.target.value }))}
              style={{
                width: "100%", background: "#0f172a", color: TEXT, border: `1px solid ${BORDER}`,
                borderRadius: 4, padding: "4px 8px", fontSize: 10, fontFamily: FONT,
              }}>
              <option value="">All types</option>
              {allTypes.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ color: MUTED, fontSize: 10, cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }}>
              <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
              Auto-refresh (5s)
            </label>
          </div>
          {(filter.agent || filter.type) && (
            <button onClick={() => setFilter({ agent: "", type: "" })}
              style={{
                marginTop: 8, width: "100%", background: "transparent", color: ACCENT,
                border: `1px solid ${ACCENT}44`, borderRadius: 4, padding: "4px 0",
                fontSize: 10, cursor: "pointer", fontFamily: FONT,
              }}>Clear Filters</button>
          )}
        </Panel>
      </div>

      {/* RIGHT: Feed */}
      <Panel style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1 }}>
            AUDIT FEED {loading ? "..." : ""} · {entries.length} entries
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {autoRefresh && <span style={{ color: GREEN, fontSize: 8 }}>● LIVE</span>}
          </div>
        </div>
        {entries.length === 0 && !loading ? (
          <div style={{ color: MUTED, fontSize: 11, textAlign: "center", marginTop: 40 }}>No audit entries found</div>
        ) : entries.map((e, i) => (
          <div key={`${e.id}-${i}`} className="msg-in" style={{
            background: "#0f172a", borderRadius: 6, padding: "8px 12px", marginBottom: 6,
            borderLeft: `3px solid ${eventColor(e.event_type)}`,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Badge color={eventColor(e.event_type)}>{e.event_type}</Badge>
                <span style={{ color: getAgentColor(e.agent_name + "-agent"), fontSize: 10, fontWeight: 600 }}>
                  {e.agent_name}
                </span>
                {e.severity && e.severity !== "info" && (
                  <Badge color={severityColor(e.severity)}>{e.severity.toUpperCase()}</Badge>
                )}
              </div>
              <span style={{ color: MUTED, fontSize: 9 }}>
                {e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "—"}
              </span>
            </div>
            {e.action && (
              <div style={{ color: "#94a3b8", fontSize: 10, marginBottom: 2 }}>
                <span style={{ color: MUTED }}>action:</span> {e.action}
              </div>
            )}
            {e.details && (
              <div style={{ color: "#64748b", fontSize: 10, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                {String(e.details).slice(0, 300)}
                {String(e.details).length > 300 ? "..." : ""}
              </div>
            )}
            {e.changes && e.changes.length > 0 && (
              <div style={{ color: YELLOW, fontSize: 10 }}>changes: {e.changes.join(", ")}</div>
            )}
            {e.tools && e.tools.length > 0 && (
              <div style={{ color: "#64748b", fontSize: 9, marginTop: 2 }}>
                tools: {e.tools.join(", ").slice(0, 200)}
              </div>
            )}
          </div>
        ))}
      </Panel>
    </div>
  );
}

// ── Tab: Pipeline ────────────────────────────────────────

function PipelineTab({ agents }) {
  const ORG = [
    { role: "SCHEDULER", agents: [], description: "CronJobs trigger periodic tasks", icon: "clock" },
    { role: "ROUTER", agents: ["commander-agent"], description: "Routes requests to C-suite", icon: "hex" },
    { role: "C-SUITE", agents: ["ceo-agent", "coo-agent", "cso-agent", "pm-agent"], description: "Strategy, ops, security, project management", icon: "crown" },
    { role: "WORKERS", agents: ["prospecting-agent"], description: "Execute tasks (search, build, outreach)", icon: "hammer" },
    { role: "INFRASTRUCTURE", agents: ["audit-logger", "resource-governor", "hardening-agent", "agent-policy-server"], description: "Safety, budgets, logging, patterns", icon: "shield" },
  ];

  const agentMap = {};
  agents.forEach(a => { agentMap[a.metadata?.name] = a; });

  const getStatus = (name) => {
    const a = agentMap[name];
    if (!a) return { label: "NOT DEPLOYED", color: MUTED };
    const conditions = a.status?.conditions || [];
    if (conditions.some(c => c.type === "Ready" && c.status === "True")) return { label: "READY", color: GREEN };
    if (conditions.some(c => c.type === "Accepted" && c.status === "True")) return { label: "ACCEPTED", color: YELLOW };
    return { label: "UNKNOWN", color: MUTED };
  };

  const getTools = (name) => {
    const a = agentMap[name];
    if (!a) return [];
    return (a.spec?.declarative?.tools || []).map(t => {
      if (t.type === "McpServer") {
        const m = t.mcpServer;
        return `${m.name}/${(m.toolNames || []).join(",")}`;
      }
      if (t.type === "Agent") return `a2a:${t.agent?.name}`;
      return t.type;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 4, overflowY: "auto", height: "100%" }} className="fade-in">
      <Panel>
        <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1, marginBottom: 8 }}>PIPELINE FLOW</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10, color: "#64748b", flexWrap: "wrap" }}>
          {["Scheduler", "->", "Commander", "->", "C-Suite", "->", "Workers", "->", "Audit"].map((s, i) => (
            <span key={i} style={{ color: s === "->" ? MUTED : ACCENT, fontWeight: s === "->" ? 400 : 600 }}>{s}</span>
          ))}
        </div>
      </Panel>

      {ORG.map(tier => (
        <Panel key={tier.role}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ color: ACCENT, fontSize: 12, fontWeight: 600, letterSpacing: 1 }}>{tier.role}</span>
            <span style={{ color: MUTED, fontSize: 10 }}>— {tier.description}</span>
          </div>
          {tier.agents.length === 0 ? (
            <div style={{ color: MUTED, fontSize: 10, paddingLeft: 24 }}>
              {tier.role === "SCHEDULER" ? "3 CronJobs: cso-audit (6h), pm-prospecting (daily 9am), coo-status (4h)" : "No agents"}
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
              {tier.agents.map(name => {
                const status = getStatus(name);
                const tools = getTools(name);
                return (
                  <div key={name} style={{
                    background: "#0f172a", borderRadius: 6, padding: "10px 12px",
                    borderLeft: `3px solid ${getAgentColor(name)}`,
                  }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: getAgentColor(name), fontSize: 14 }}>{getAgentEmoji(name)}</span>
                        <span style={{ color: TEXT, fontSize: 11, fontWeight: 600 }}>{name}</span>
                      </div>
                      <Badge color={status.color}>{status.label}</Badge>
                    </div>
                    {tools.length > 0 && (
                      <div style={{ fontSize: 9, color: "#64748b", lineHeight: 1.5 }}>
                        {tools.map((t, i) => (
                          <div key={i} style={{ display: "flex", gap: 4 }}>
                            <span style={{ color: MUTED }}>*</span> {t}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      ))}

      {(() => {
        const pipelineAgents = new Set(ORG.flatMap(t => t.agents));
        const others = agents.filter(a => !pipelineAgents.has(a.metadata?.name));
        if (others.length === 0) return null;
        return (
          <Panel>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <span style={{ color: MUTED, fontSize: 12, fontWeight: 600, letterSpacing: 1 }}>OTHER / LEGACY</span>
              <span style={{ color: MUTED, fontSize: 10 }}>— Not part of the active pipeline</span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {others.map(a => {
                const name = a.metadata?.name;
                const status = getStatus(name);
                return (
                  <div key={name} style={{
                    background: "#0f172a", borderRadius: 4, padding: "4px 10px",
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
                    <span style={{ color: getAgentColor(name), fontSize: 10 }}>{name}</span>
                    <span style={{ color: status.color, fontSize: 8 }}>●</span>
                  </div>
                );
              })}
            </div>
          </Panel>
        );
      })()}
    </div>
  );
}

// ── Tab: Tests ───────────────────────────────────────────

function TestsTab() {
  const [tests, setTests] = useState([]);
  const [results, setResults] = useState({});
  const [running, setRunning] = useState(null);

  useEffect(() => {
    fetch("/api/test").then(r => r.json()).then(d => setTests(d.tests || [])).catch(() => {});
  }, []);

  const runTest = async (testId) => {
    setRunning(testId);
    setResults(r => ({ ...r, [testId]: { status: "running" } }));
    try {
      const res = await fetch("/api/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ testId }),
      });
      const data = await res.json();
      setResults(r => ({ ...r, [testId]: data }));
    } catch (e) {
      setResults(r => ({ ...r, [testId]: { status: "fail", error: e.message } }));
    }
    setRunning(null);
  };

  const statusIcon = (s) => {
    if (s === "running") return "~";
    if (s === "pass") return "OK";
    if (s === "warning") return "!!";
    if (s === "fail") return "X";
    return "o";
  };

  const statusColor = (s) => {
    if (s === "running") return ACCENT;
    if (s === "pass") return GREEN;
    if (s === "warning") return YELLOW;
    if (s === "fail") return RED;
    return MUTED;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, height: "100%", overflowY: "auto" }} className="fade-in">
      <Panel>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ color: MUTED, fontSize: 10, letterSpacing: 1 }}>TEST SUITE</div>
          <button onClick={() => tests.forEach(t => !running && runTest(t.id))} disabled={!!running}
            style={{
              background: running ? "transparent" : "rgba(99,102,241,0.2)",
              color: running ? MUTED : ACCENT,
              border: `1px solid ${running ? BORDER : "rgba(99,102,241,0.4)"}`,
              borderRadius: 4, padding: "4px 12px", fontSize: 10,
              cursor: running ? "not-allowed" : "pointer", fontFamily: FONT,
            }}>
            {running ? "RUNNING..." : "RUN ALL >>"}
          </button>
        </div>
        <div style={{ color: "#64748b", fontSize: 10, lineHeight: 1.5, marginBottom: 10 }}>
          Each test sends a real request through the full pipeline: scheduler to commander to agent to tools to audit log.
          Tests verify that agents actually call their tools and produce structured output.
        </div>
      </Panel>

      {tests.map(test => {
        const result = results[test.id];
        const status = result?.status || "pending";

        return (
          <Panel key={test.id}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ color: statusColor(status), fontSize: 14, fontWeight: 600 }}>{statusIcon(status)}</span>
                <span style={{ color: TEXT, fontSize: 12, fontWeight: 600 }}>{test.name}</span>
                <Badge color={getAgentColor(test.agent)}>{test.agent}</Badge>
              </div>
              <button onClick={() => runTest(test.id)} disabled={!!running}
                style={{
                  background: running ? "transparent" : `${getAgentColor(test.agent)}22`,
                  color: running ? MUTED : getAgentColor(test.agent),
                  border: `1px solid ${running ? BORDER : getAgentColor(test.agent) + "44"}`,
                  borderRadius: 4, padding: "4px 12px", fontSize: 10,
                  cursor: running ? "not-allowed" : "pointer", fontFamily: FONT,
                }}>
                {running === test.id ? "~ Running..." : "Run >>"}
              </button>
            </div>
            <div style={{ color: MUTED, fontSize: 10, marginBottom: 8 }}>{test.description}</div>

            {result && result.status !== "running" && (
              <div style={{
                background: "#0f172a", borderRadius: 6, padding: "10px 12px",
                borderLeft: `3px solid ${statusColor(status)}`,
                marginTop: 6,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <Badge color={statusColor(status)}>{status.toUpperCase()}</Badge>
                  {result.error && <span style={{ color: RED, fontSize: 10 }}>{result.error}</span>}
                </div>
                {result.result && (
                  <div style={{ color: "#94a3b8", fontSize: 10, lineHeight: 1.6, whiteSpace: "pre-wrap", maxHeight: 400, overflowY: "auto" }}>
                    {result.result}
                  </div>
                )}
              </div>
            )}
          </Panel>
        );
      })}
    </div>
  );
}

// ── Tab: Roadmap ─────────────────────────────────────────

// Strategic milestones — human-owned, update here when priorities change.
// Status: "done" | "active" | "next" | "pending"
const ROADMAP = [
  {
    phase: "SAFETY",
    color: "#f87171",
    items: [
      { status: "done",    label: "Phase 2: Audit logger",              note: "watches Agent CRs, MCP tools" },
      { status: "done",    label: "Phase 3: Resource governor",          note: "MCP running :8093" },
      { status: "done",    label: "Phase 4: Hardening loop",             note: "5min interval, GitHub PRs" },
      { status: "done",    label: "Phase 1: Admission webhook",          note: "deployed, audit mode" },
      { status: "done",    label: "HITL pipeline end-to-end",            note: "CSO audit→enforce→approve→execute" },
      { status: "done",    label: "Flip Phase 1 → enforce mode",         note: "rogue agents blocked, clean list" },
      { status: "pending", label: "require_hitl_label_for_mcp: true",    note: "after labeling existing agents" },
      { status: "pending", label: "Calico CNI for NetworkPolicy",        note: "Flannel doesn't enforce" },
    ],
  },
  {
    phase: "AGENT ORG",
    color: "#a78bfa",
    items: [
      { status: "done",    label: "commander-agent (thin router)",       note: "HITL_RESUME routing" },
      { status: "done",    label: "ceo-agent",                           note: "vision/strategy, no tools" },
      { status: "done",    label: "coo-agent",                           note: "audit read + Slack" },
      { status: "done",    label: "cso-agent",                           note: "AUDIT/ENFORCE/EXECUTE tested" },
      { status: "done",    label: "pm-agent",                            note: "backlog + prospecting delegation" },
      { status: "done",    label: "hardening-agent",                     note: "patterns every 5min, PRs" },
      { status: "next",    label: "cfo-agent",                           note: "resource-governor MCP ready" },
    ],
  },
  {
    phase: "WORKER PIPELINE",
    color: "#34d399",
    items: [
      { status: "done",    label: "prospecting-agent",                   note: "search_find_businesses + web" },
      { status: "done",    label: "site-builder-agent",                  note: "deployed, tested — test-plumbing-demo live" },
      { status: "next",    label: "outreach-agent",                      note: "HITL-gated cold emails" },
      { status: "pending", label: "follow-up-agent",                     note: "lead nurturing" },
      { status: "next",    label: "PM → prospect → site → outreach",    note: "PM can now delegate to both workers" },
    ],
  },
  {
    phase: "INFRASTRUCTURE",
    color: "#38bdf8",
    items: [
      { status: "done",    label: "github-mcp 7 tools",                  note: "branch + PR creation" },
      { status: "done",    label: "hitl-tool-server",                    note: "Slack buttons, severity timeouts" },
      { status: "done",    label: "api/hitl.js bugs fixed",              note: "message/send, kind, namespace" },
      { status: "pending", label: "kagent memory on all agents",         note: "context persistence" },
      { status: "pending", label: "business metrics in dashboard",       note: "leads found, emails, revenue" },
      { status: "pending", label: "pin image digests",                   note: "reproducible deploys" },
    ],
  },
];

const STATUS_META = {
  done:    { icon: "✓", color: "#22c55e", label: "DONE" },
  active:  { icon: "▶", color: "#facc15", label: "ACTIVE" },
  next:    { icon: "→", color: "#a78bfa", label: "NEXT" },
  pending: { icon: "○", color: "#334155", label: "PENDING" },
};

function RoadmapTab() {
  const [tasks, setTasks] = useState([]);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const isMobile = useIsMobile();

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch("/api/audit?n=200");
        const d = await r.json();
        const lines = (d.entries || d.result || "").trim().split("\n").filter(Boolean);
        const parsed = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
        // Only pm-agent task lifecycle entries
        const taskEntries = parsed.filter(e =>
          e.action && (e.action.startsWith("task_") || ["task_created","task_done","task_step_done","task_blocked","task_cancelled"].includes(e.action))
        );
        // Deduplicate by task id — keep latest status per task
        const byId = {};
        taskEntries.forEach(e => {
          const id = e.details?.task_id || e.id;
          if (!byId[id] || new Date(e.timestamp) > new Date(byId[id].timestamp)) byId[id] = e;
        });
        setTasks(Object.values(byId).sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 30));
      } catch {
        setTasks([]);
      } finally {
        setLoadingTasks(false);
      }
    };
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const taskStatusColor = (action) => {
    if (!action) return MUTED;
    if (action === "task_done") return "#22c55e";
    if (action === "task_blocked") return "#ef4444";
    if (action === "task_cancelled") return "#f87171";
    if (action === "task_created") return "#a78bfa";
    return "#facc15"; // step_done / in-progress
  };

  const taskStatusLabel = (action) => {
    const map = { task_created: "QUEUED", task_done: "DONE", task_blocked: "BLOCKED", task_cancelled: "CANCELLED", task_step_done: "IN PROGRESS" };
    return map[action] || action?.replace("task_", "").toUpperCase();
  };

  // Count by phase
  const summary = ROADMAP.map(phase => ({
    phase: phase.phase,
    color: phase.color,
    done: phase.items.filter(i => i.status === "done").length,
    total: phase.items.length,
  }));

  return (
    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 380px", gap: 12, height: "100%", overflow: "hidden" }}>

      {/* Left: Strategic Roadmap */}
      <div style={{ overflowY: "auto", paddingRight: 4 }}>
        {/* Progress summary bar */}
        <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
          {summary.map(s => (
            <div key={s.phase} style={{ background: PANEL, border: `1px solid ${BORDER}`, borderRadius: 6, padding: "6px 12px", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ color: s.color, fontSize: 9, letterSpacing: 1 }}>{s.phase}</span>
              <div style={{ width: 60, height: 3, background: BORDER, borderRadius: 2, overflow: "hidden" }}>
                <div style={{ width: `${(s.done / s.total) * 100}%`, height: "100%", background: s.color, borderRadius: 2, transition: "width 0.4s" }} />
              </div>
              <span style={{ color: MUTED, fontSize: 9 }}>{s.done}/{s.total}</span>
            </div>
          ))}
        </div>

        {/* Phase sections */}
        {ROADMAP.map(phase => (
          <div key={phase.phase} style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <div style={{ width: 3, height: 16, background: phase.color, borderRadius: 2 }} />
              <span style={{ color: phase.color, fontSize: 10, fontWeight: 600, letterSpacing: 2 }}>{phase.phase}</span>
              <div style={{ flex: 1, height: 1, background: BORDER }} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {phase.items.map((item, i) => {
                const meta = STATUS_META[item.status];
                return (
                  <div key={i} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    background: item.status === "next" ? "rgba(167,139,250,0.06)" : "transparent",
                    border: `1px solid ${item.status === "next" ? "rgba(167,139,250,0.2)" : "transparent"}`,
                    borderRadius: 4, padding: "5px 8px",
                    opacity: item.status === "pending" ? 0.45 : 1,
                  }}>
                    <span style={{ color: meta.color, fontSize: 11, width: 12, textAlign: "center", flexShrink: 0 }}>{meta.icon}</span>
                    <span style={{ color: item.status === "done" ? MUTED : TEXT, fontSize: 11, textDecoration: item.status === "done" ? "line-through" : "none", flex: 1 }}>{item.label}</span>
                    {item.note && <span style={{ color: MUTED, fontSize: 9, letterSpacing: 0.5 }}>{item.note}</span>}
                    {item.status === "next" && <span style={{ color: "#a78bfa", fontSize: 8, letterSpacing: 1, background: "rgba(167,139,250,0.15)", padding: "1px 5px", borderRadius: 3 }}>NEXT</span>}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Right: Live Task Log from pm-agent */}
      <div style={{ background: PANEL, border: `1px solid ${BORDER}`, borderRadius: 8, display: "flex", flexDirection: "column", overflow: "hidden", maxHeight: isMobile ? 320 : undefined }}>
        <div style={{ padding: "10px 14px", borderBottom: `1px solid ${BORDER}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ color: ACCENT, fontSize: 10, letterSpacing: 1.5 }}>LIVE TASK LOG</span>
          <span style={{ color: MUTED, fontSize: 9 }}>pm-agent • 15s refresh</span>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {loadingTasks && (
            <div style={{ padding: 16, color: MUTED, fontSize: 10, textAlign: "center" }}>loading...</div>
          )}
          {!loadingTasks && tasks.length === 0 && (
            <div style={{ padding: 16, color: MUTED, fontSize: 10, textAlign: "center" }}>
              no task entries yet<br />
              <span style={{ fontSize: 9, opacity: 0.6 }}>pm-agent writes task_ audit entries</span>
            </div>
          )}
          {tasks.map((t, i) => (
            <div key={i} style={{
              padding: "7px 14px",
              borderBottom: `1px solid ${BORDER}`,
              display: "flex", flexDirection: "column", gap: 3,
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ color: taskStatusColor(t.action), fontSize: 9, letterSpacing: 1 }}>
                  {taskStatusLabel(t.action)}
                </span>
                {t.details?.priority && (
                  <span style={{ color: MUTED, fontSize: 9 }}>{t.details.priority}</span>
                )}
              </div>
              <span style={{ color: TEXT, fontSize: 10 }}>
                {t.details?.task || t.details?.description || t.agent_name || "—"}
              </span>
              {(t.details?.step || t.details?.result) && (
                <span style={{ color: MUTED, fontSize: 9, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {t.details.step || t.details.result}
                </span>
              )}
              <span style={{ color: MUTED, fontSize: 8 }}>
                {t.timestamp ? new Date(t.timestamp).toLocaleString() : ""}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main Dashboard ───────────────────────────────────────

const TABS = [
  { id: "agents",  label: "AGENTS",   icon: "[]" },
  { id: "audit",   label: "AUDIT FEED", icon: ">>" },
  { id: "roadmap", label: "ROADMAP",  icon: "#" },
  { id: "pipeline", label: "PIPELINE", icon: "|>" },
  { id: "tests",   label: "TESTS",    icon: "ok" },
];

function Dashboard() {
  const [tab, setTab] = useState("agents");
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);
  const [lastPoll, setLastPoll] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sessionMap, setSessionMap] = useState({});
  const [layout, setLayout] = useState({});
  const isMobile = useIsMobile();

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch("/api/proxy/apis/kagent.dev/v1alpha2/namespaces/kagent/agents");
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        const items = Array.isArray(data?.items) ? data.items : [];
        setAgents(items);
        setLayout(computeLayout(items));
        setError(null);
        setLastPoll(new Date().toLocaleTimeString());
      } catch (e) { setError(e.message); }
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const pollSessions = async () => {
      try {
        const res = await fetch("/api/proxy/api/v1/namespaces/kagent/services/kagent-controller:8083/proxy/api/sessions?user_id=admin@kagent.dev");
        if (!res.ok) return;
        const data = await res.json();
        const sessions = Array.isArray(data) ? data : data?.sessions || [];
        const newMap = {};
        sessions.forEach(s => {
          const agentName = s.agentRef?.name || s.agent_ref?.name;
          if (!agentName) return;
          if (!newMap[agentName]) newMap[agentName] = { taskCount: 0, isActive: false };
          newMap[agentName].taskCount += 1;
          const updated = new Date(s.updatedAt || s.updated_at || 0);
          if ((Date.now() - updated.getTime()) < 30000) newMap[agentName].isActive = true;
        });
        setSessionMap(newMap);
      } catch {}
    };
    pollSessions();
    const t = setInterval(pollSessions, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{
      background: BG, minHeight: "100vh", color: TEXT,
      fontFamily: FONT, padding: isMobile ? "8px 8px 64px" : 12, boxSizing: "border-box",
    }}>
      <style>{GLOBAL_CSS}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, padding: "0 4px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: ACCENT, fontSize: isMobile ? 14 : 16, fontWeight: 600, letterSpacing: 2 }}>AUTOBOT</span>
          <span style={{ color: BORDER, fontSize: 14 }}>//</span>
          <span style={{ color: MUTED, fontSize: isMobile ? 10 : 11 }}>COMMAND CENTER</span>
        </div>

        {/* Tabs — desktop only */}
        {!isMobile && (
          <div style={{ display: "flex", gap: 2 }}>
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)} style={{
                background: tab === t.id ? "rgba(99,102,241,0.15)" : "transparent",
                color: tab === t.id ? ACCENT : MUTED,
                border: `1px solid ${tab === t.id ? "rgba(99,102,241,0.3)" : "transparent"}`,
                borderRadius: 4, padding: "5px 12px", cursor: "pointer",
                fontFamily: FONT, fontSize: 10, letterSpacing: 1,
                transition: "all 0.15s",
              }}>
                {t.icon} {t.label}
              </button>
            ))}
          </div>
        )}

        {/* Status */}
        <div style={{ display: "flex", alignItems: "center", gap: isMobile ? 8 : 16, fontSize: 10 }}>
          <span style={{ color: error ? RED : GREEN }}>{error ? `ERR` : "● LIVE"}</span>
          {!isMobile && <span style={{ color: MUTED }}>{lastPoll || "—"}</span>}
          <span style={{ color: ACCENT }}>{agents.length}{isMobile ? "" : " AGENTS"}</span>
        </div>
      </div>

      {/* Tab Content */}
      <div style={{ height: isMobile ? "calc(100vh - 48px - 64px)" : "calc(100vh - 56px)" }}>
        {tab === "agents" && (
          <AgentsTab agents={agents} layout={layout} sessionMap={sessionMap}
            setSessionMap={setSessionMap} selected={selected} setSelected={setSelected} />
        )}
        {tab === "audit" && <AuditTab />}
        {tab === "roadmap" && <RoadmapTab />}
        {tab === "pipeline" && <PipelineTab agents={agents} />}
        {tab === "tests" && <TestsTab />}
      </div>

      {/* Mobile bottom tab bar */}
      {isMobile && (
        <div style={{
          position: "fixed", bottom: 0, left: 0, right: 0,
          background: PANEL, borderTop: `1px solid ${BORDER}`,
          display: "flex", zIndex: 100,
        }}>
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              flex: 1, padding: "10px 4px 12px", cursor: "pointer",
              background: tab === t.id ? "rgba(99,102,241,0.15)" : "transparent",
              color: tab === t.id ? ACCENT : MUTED,
              border: "none", borderTop: `2px solid ${tab === t.id ? ACCENT : "transparent"}`,
              fontFamily: FONT, fontSize: 8, letterSpacing: 0.5,
              display: "flex", flexDirection: "column", alignItems: "center", gap: 3,
            }}>
              <span style={{ fontSize: 16 }}>{t.icon}</span>
              <span>{t.label.split(" ")[0]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── App (Auth Gate) ──────────────────────────────────────

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    fetch("/api/proxy/apis/kagent.dev/v1alpha2/namespaces/kagent/agents")
      .then(r => { setAuthed(r.status !== 401); })
      .catch(() => setAuthed(false))
      .finally(() => setCheckingAuth(false));
  }, []);

  if (checkingAuth) return (
    <div style={{ background: BG, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: MUTED, fontFamily: "monospace", fontSize: 11, letterSpacing: 2 }}>INITIALIZING...</div>
    </div>
  );

  if (!authed) return <LoginScreen onLogin={() => setAuthed(true)} />;
  return <Dashboard />;
}
