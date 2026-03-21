import { useState, useEffect, useRef, useCallback } from "react";

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
      if (res.ok) {
        onLogin();
      } else {
        setError("Invalid password");
      }
    } catch (e) {
      setError("Connection error");
    } finally {
      setLoading(false);
    }
  };

  const onKey = e => { if (e.key === "Enter") submit(); };

  return (
    <div style={{
      background: "#080f1a",
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');`}</style>
      <div style={{ textAlign: "center", width: 320 }}>
        <div style={{ color: "#a78bfa", fontSize: 28, fontWeight: 600, letterSpacing: 4, marginBottom: 8 }}>AUTOBOT</div>
        <div style={{ color: "#334155", fontSize: 11, letterSpacing: 2, marginBottom: 40 }}>COMMAND CENTER</div>
        <div style={{
          background: "#0a1628",
          border: "1px solid #1e293b",
          borderRadius: 8,
          padding: 24,
        }}>
          <div style={{ color: "#334155", fontSize: 10, letterSpacing: 1, marginBottom: 12, textAlign: "left" }}>ACCESS CODE</div>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={onKey}
            autoFocus
            placeholder="enter password"
            style={{
              width: "100%",
              background: "#0f172a",
              border: `1px solid ${error ? "#ef4444" : "#1e293b"}`,
              borderRadius: 6,
              color: "#e2e8f0",
              padding: "10px 12px",
              fontSize: 12,
              fontFamily: "inherit",
              boxSizing: "border-box",
              outline: "none",
              marginBottom: 12,
            }}
          />
          {error && <div style={{ color: "#ef4444", fontSize: 10, marginBottom: 10, textAlign: "left" }}>{error}</div>}
          <button
            onClick={submit}
            disabled={loading || !password.trim()}
            style={{
              width: "100%",
              background: loading || !password.trim() ? "transparent" : "rgba(99,102,241,0.2)",
              color: loading || !password.trim() ? "#334155" : "#a78bfa",
              border: `1px solid ${loading || !password.trim() ? "#1e293b" : "rgba(99,102,241,0.4)"}`,
              borderRadius: 6,
              padding: "10px 0",
              cursor: loading ? "not-allowed" : "pointer",
              fontFamily: "inherit",
              fontSize: 12,
              letterSpacing: 1,
            }}
          >
            {loading ? "AUTHENTICATING..." : "ENTER ▶"}
          </button>
        </div>
      </div>
    </div>
  );
}

const POLL_MS = 3000;
const SESSION_POLL_MS = 5000;

const FIXED_POSITIONS = {
  "commander-agent": { x: 0, y: 0 },
};

const RING_RADIUS = 180;

function getAgentColor(name) {
  if (name === "commander-agent") return "#a78bfa";
  if (name.includes("number")) return "#38bdf8";
  if (name.includes("sum")) return "#34d399";
  if (name.includes("k8s") || name.includes("helm") || name.includes("kgateway")) return "#fb923c";
  if (name.includes("observ") || name.includes("promql") || name.includes("cilium")) return "#f472b6";
  if (name.includes("argo")) return "#facc15";
  const hash = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
  const colors = ["#38bdf8", "#34d399", "#fb923c", "#f472b6", "#facc15", "#a78bfa", "#f87171"];
  return colors[hash % colors.length];
}

function getAgentEmoji(name) {
  if (name === "commander-agent") return "⬡";
  if (name.includes("number")) return "◈";
  if (name.includes("sum")) return "∑";
  if (name.includes("k8s")) return "⎔";
  if (name.includes("helm")) return "◉";
  if (name.includes("observ") || name.includes("promql")) return "◎";
  if (name.includes("cilium")) return "⬢";
  if (name.includes("argo")) return "⟳";
  if (name.includes("ping")) return "◌";
  return "◆";
}

function computeLayout(agents) {
  const nodes = {};
  const commander = agents.find(a => a.metadata?.name === "commander-agent");
  if (commander) {
    nodes["commander-agent"] = { x: 0, y: 0 };
  }
  const others = agents.filter(a => a.metadata?.name !== "commander-agent");
  const count = others.length;
  others.forEach((a, i) => {
    const angle = (i / Math.max(count, 1)) * 2 * Math.PI - Math.PI / 2;
    const r = count <= 4 ? RING_RADIUS : count <= 8 ? RING_RADIUS * 1.1 : RING_RADIUS * 1.25;
    nodes[a.metadata.name] = {
      x: Math.cos(angle) * r,
      y: Math.sin(angle) * r,
    };
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
  const lastOutput = sessionData?.lastOutput;
  const taskCount = sessionData?.taskCount || 0;
  const isActive = sessionData?.isActive;

  const size = isCommander ? 54 : 42;
  const cx = pos.x;
  const cy = pos.y;

  return (
    <g
      onClick={() => onClick(name)}
      style={{ cursor: "pointer" }}
      transform={`translate(${cx}, ${cy})`}
    >
      {isActive && (
        <circle r={size / 2 + 10} fill="none" stroke={color} strokeWidth="1" opacity="0.3">
          <animate attributeName="r" values={`${size / 2 + 6};${size / 2 + 16};${size / 2 + 6}`} dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.4;0;0.4" dur="2s" repeatCount="indefinite" />
        </circle>
      )}
      <circle
        r={size / 2}
        fill="#0f172a"
        stroke={selected ? "#fff" : color}
        strokeWidth={selected ? 2 : isCommander ? 1.5 : 1}
        opacity={isReady || isAccepted ? 1 : 0.4}
      />
      <text
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={isCommander ? 20 : 16}
        fill={color}
        y={-2}
        style={{ fontFamily: "monospace", userSelect: "none" }}
      >
        {emoji}
      </text>
      {taskCount > 0 && (
        <g transform={`translate(${size / 2 - 6}, ${-size / 2 + 6})`}>
          <circle r={8} fill={color} />
          <text textAnchor="middle" dominantBaseline="central" fontSize={8} fill="#0f172a" fontWeight="600">
            {taskCount > 99 ? "99+" : taskCount}
          </text>
        </g>
      )}
      <text
        y={size / 2 + 14}
        textAnchor="middle"
        fontSize={9}
        fill={selected ? "#fff" : "#94a3b8"}
        style={{ fontFamily: "monospace", userSelect: "none" }}
      >
        {name.replace("-agent", "").slice(0, 14)}
      </text>
      {lastOutput && (
        <text
          y={size / 2 + 26}
          textAnchor="middle"
          fontSize={8}
          fill={color}
          opacity={0.8}
          style={{ fontFamily: "monospace", userSelect: "none" }}
        >
          {String(lastOutput).slice(0, 16)}
        </text>
      )}
    </g>
  );
}

function Dashboard() {
  const [agents, setAgents] = useState([]);
  const [error, setError] = useState(null);
  const [lastPoll, setLastPoll] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sessionMap, setSessionMap] = useState({});
  const [messages, setMessages] = useState([
    { role: "assistant", text: "👋 Hi! I'm your Commander. Tell me about a business opportunity you want to pursue and I'll help create a plan and build an agent army to execute it." }
  ]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [layout, setLayout] = useState({});
  const [activityLog, setActivityLog] = useState([]);
  const chatRef = useRef(null);
  const svgRef = useRef(null);

  // Poll agents
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
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, []);

  // Poll sessions for activity
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
          const isRecent = (Date.now() - updated.getTime()) < 30000;
          if (isRecent) newMap[agentName].isActive = true;
        });
        setSessionMap(newMap);
      } catch (_) {}
    };
    pollSessions();
    const t = setInterval(pollSessions, SESSION_POLL_MS);
    return () => clearInterval(t);
  }, []);

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
    } finally {
      setThinking(false);
    }
  };

  const onKey = e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const selectedAgent = selected ? agents.find(a => a.metadata?.name === selected) : null;
  const selectedSession = selected ? sessionMap[selected] : null;

  // SVG viewport
  const SVG_W = 540;
  const SVG_H = 460;
  const CX = SVG_W / 2;
  const CY = SVG_H / 2 - 10;

  return (
    <div style={{
      background: "#080f1a",
      minHeight: "100vh",
      color: "#e2e8f0",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      padding: 12,
      boxSizing: "border-box",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }
        textarea:focus { outline: none; }
        .msg-in { animation: fadeUp 0.2s ease; }
        @keyframes fadeUp { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:translateY(0); } }
        .blink { animation: blink 1s step-end infinite; }
        @keyframes blink { 50% { opacity: 0; } }
        .scan-line {
          position: absolute; inset: 0; pointer-events: none; z-index: 0;
          background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,255,180,0.015) 2px, rgba(0,255,180,0.015) 4px);
        }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, padding: "0 4px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "#a78bfa", fontSize: 16, fontWeight: 600, letterSpacing: 2 }}>AUTOBOT</span>
          <span style={{ color: "#1e293b", fontSize: 14 }}>//</span>
          <span style={{ color: "#334155", fontSize: 11 }}>COMMAND CENTER</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 10 }}>
          <span style={{ color: error ? "#ef4444" : "#22c55e" }}>
            {error ? `⚠ ERR ${error}` : `● LIVE`}
          </span>
          <span style={{ color: "#334155" }}>{lastPoll || "—"}</span>
          <span style={{ color: "#a78bfa" }}>{agents.length} AGENTS</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, height: "calc(100vh - 56px)" }}>

        {/* LEFT PANEL */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10, flex: "0 0 560px" }}>

          {/* Agent Graph */}
          <div style={{
            background: "#0a1628",
            border: "1px solid #1e293b",
            borderRadius: 8,
            position: "relative",
            overflow: "hidden",
          }}>
            <div className="scan-line" />
            <svg ref={svgRef} width={SVG_W} height={SVG_H} style={{ display: "block", position: "relative", zIndex: 1 }}>
              {/* Grid dots */}
              {Array.from({ length: 12 }).map((_, row) =>
                Array.from({ length: 15 }).map((_, col) => (
                  <circle key={`${row}-${col}`} cx={col * 38 + 10} cy={row * 38 + 10} r={0.8} fill="#1e293b" />
                ))
              )}
              {/* Edges from commander to all others */}
              {agents.filter(a => a.metadata?.name !== "commander-agent").map(a => {
                const name = a.metadata?.name;
                const pos = layout[name];
                const cmdPos = layout["commander-agent"];
                if (!pos || !cmdPos) return null;
                const color = getAgentColor(name);
                return (
                  <line
                    key={name}
                    x1={CX + cmdPos.x} y1={CY + cmdPos.y}
                    x2={CX + pos.x} y2={CY + pos.y}
                    stroke={color}
                    strokeWidth={0.5}
                    opacity={0.2}
                    strokeDasharray="4 4"
                  />
                );
              })}
              {/* Nodes */}
              {agents.map(a => {
                const name = a.metadata?.name;
                const pos = layout[name];
                if (!pos) return null;
                return (
                  <AgentNode
                    key={name}
                    agent={a}
                    pos={{ x: CX + pos.x, y: CY + pos.y }}
                    selected={selected === name}
                    onClick={setSelected}
                    sessionData={sessionMap[name]}
                  />
                );
              })}
              {thinking && (
                <text x={CX} y={SVG_H - 10} textAnchor="middle" fontSize={9} fill="#6366f1" fontFamily="monospace">
                  ⟳ processing...
                </text>
              )}
            </svg>
          </div>

          {/* Agent Detail / Activity */}
          <div style={{
            background: "#0a1628",
            border: "1px solid #1e293b",
            borderRadius: 8,
            padding: 12,
            flex: 1,
            overflowY: "auto",
            fontSize: 11,
          }}>
            {selected && selectedAgent ? (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                  <span style={{ color: getAgentColor(selected), fontSize: 16 }}>{getAgentEmoji(selected)}</span>
                  <span style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 12 }}>{selected}</span>
                  <span
                    onClick={() => setSelected(null)}
                    style={{ marginLeft: "auto", color: "#334155", cursor: "pointer", fontSize: 10 }}
                  >✕ close</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  {[
                    ["TYPE", selectedAgent.spec?.type || "—"],
                    ["MODEL", selectedAgent.spec?.declarative?.modelConfig || "—"],
                    ["TASKS", sessionMap[selected]?.taskCount || 0],
                    ["STATUS", selectedAgent.status?.conditions?.find(c => c.status === "True")?.type || "unknown"],
                  ].map(([k, v]) => (
                    <div key={k} style={{ background: "#0f172a", borderRadius: 6, padding: "6px 10px" }}>
                      <div style={{ color: "#334155", fontSize: 9, marginBottom: 2 }}>{k}</div>
                      <div style={{ color: getAgentColor(selected), fontSize: 11 }}>{String(v)}</div>
                    </div>
                  ))}
                </div>
                {selectedAgent.spec?.declarative?.systemMessage && (
                  <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 10px" }}>
                    <div style={{ color: "#334155", fontSize: 9, marginBottom: 4 }}>SYSTEM MESSAGE</div>
                    <div style={{ color: "#64748b", fontSize: 10, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
                      {selectedAgent.spec.declarative.systemMessage.slice(0, 300)}
                      {selectedAgent.spec.declarative.systemMessage.length > 300 ? "…" : ""}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div style={{ color: "#334155", fontSize: 10, marginBottom: 8, letterSpacing: 1 }}>ACTIVITY LOG</div>
                {activityLog.length === 0 ? (
                  <div style={{ color: "#1e293b", fontSize: 11 }}>No activity yet — send a message to commander</div>
                ) : activityLog.map((e, i) => (
                  <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "flex-start" }}>
                    <span style={{ color: "#334155", whiteSpace: "nowrap", fontSize: 9, paddingTop: 1 }}>{e.time}</span>
                    <span style={{ color: getAgentColor(e.agent), fontSize: 9, whiteSpace: "nowrap" }}>{e.agent.replace("-agent", "")}</span>
                    <span style={{ color: "#64748b", fontSize: 10, lineHeight: 1.4 }}>{e.text}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* RIGHT: Chat */}
        <div style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          background: "#0a1628",
          border: "1px solid #1e293b",
          borderRadius: 8,
          padding: 12,
          minWidth: 0,
          position: "relative",
          overflow: "hidden",
        }}>
          <div className="scan-line" />
          <div style={{ color: "#334155", fontSize: 10, marginBottom: 10, letterSpacing: 1, position: "relative", zIndex: 1 }}>
            COMMANDER CHAT {sessionId ? `· ${sessionId.slice(0, 8)}…` : "· new session"}
          </div>

          {/* Messages */}
          <div ref={chatRef} style={{ flex: 1, overflowY: "auto", marginBottom: 10, position: "relative", zIndex: 1 }}>
            {messages.map((m, i) => (
              <div key={i} className="msg-in" style={{
                marginBottom: 12,
                display: "flex",
                flexDirection: "column",
                alignItems: m.role === "user" ? "flex-end" : "flex-start",
              }}>
                <div style={{ fontSize: 8, color: "#334155", marginBottom: 3, letterSpacing: 1 }}>
                  {m.role === "user" ? "YOU" : "COMMANDER"}
                </div>
                <div style={{
                  maxWidth: "88%",
                  background: m.role === "user" ? "rgba(99,102,241,0.15)" : "rgba(15,23,42,0.8)",
                  border: `1px solid ${m.role === "user" ? "rgba(99,102,241,0.4)" : "#1e293b"}`,
                  borderRadius: m.role === "user" ? "10px 10px 2px 10px" : "10px 10px 10px 2px",
                  padding: "8px 12px",
                  fontSize: 11,
                  color: m.role === "user" ? "#c7d2fe" : "#94a3b8",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.6,
                }}>
                  {m.text}
                </div>
              </div>
            ))}
            {thinking && (
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
                <div style={{ fontSize: 8, color: "#334155", letterSpacing: 1 }}>COMMANDER</div>
                <div style={{ color: "#6366f1", fontSize: 11 }}>
                  <span className="blink">█</span>
                </div>
              </div>
            )}
          </div>

          {/* Input */}
          <div style={{ display: "flex", gap: 8, position: "relative", zIndex: 1 }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="send orders to commander..."
              style={{
                flex: 1,
                background: "#0f172a",
                border: "1px solid #1e293b",
                borderRadius: 6,
                color: "#e2e8f0",
                padding: "8px 10px",
                fontSize: 11,
                fontFamily: "inherit",
                resize: "none",
                height: 54,
              }}
            />
            <button
              onClick={send}
              disabled={thinking || !input.trim()}
              style={{
                background: thinking || !input.trim() ? "transparent" : "rgba(99,102,241,0.2)",
                color: thinking || !input.trim() ? "#1e293b" : "#a78bfa",
                border: `1px solid ${thinking || !input.trim() ? "#1e293b" : "rgba(99,102,241,0.4)"}`,
                borderRadius: 6,
                padding: "0 16px",
                cursor: thinking ? "not-allowed" : "pointer",
                fontFamily: "inherit",
                fontSize: 16,
                transition: "all 0.15s",
              }}
            >▶</button>
          </div>
        </div>
      </div>
    </div>
  );
}

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
    <div style={{ background: "#080f1a", minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ color: "#334155", fontFamily: "monospace", fontSize: 11, letterSpacing: 2 }}>INITIALIZING...</div>
    </div>
  );

  if (!authed) return <LoginScreen onLogin={() => setAuthed(true)} />;

  return <Dashboard />;
}