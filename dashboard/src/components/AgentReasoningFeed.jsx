import { useEffect, useRef, useState } from "react";
import { openStream } from "../api";

// Live SSE feed of agent Reason -> Act -> Observe thoughts (FRONTEND_SPEC
// component 5). Reads as a terminal printing inside a designed panel — the
// technical-depth showpiece. Auto-scrolls; capped so it never grows unbounded.

const MAX_LINES = 250;

const AGENT_COLOR = {
  cyber: "#5BA8FF",
  carbon: "#1FB57A",
  orchestrator: "#C77DFF",
  attack_simulator: "#FF2D2D",
  remediation: "#46E0A0",
  investigator: "#5BA8FF",
  system: "#6b7280",
};

const PHASE_GLYPH = {
  reason: "◆",
  act: "▸",
  observe: "●",
  done: "✓",
};

export default function AgentReasoningFeed() {
  const [lines, setLines] = useState([]);
  const scrollRef = useRef(null);
  const idRef = useRef(0);

  useEffect(() => {
    const es = openStream((event) => {
      setLines((prev) =>
        [...prev, { ...event, _id: idRef.current++ }].slice(-MAX_LINES)
      );
    });
    return () => es.close();
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div className="flex min-h-72 flex-col border border-white/10 bg-[var(--color-panel)]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="meta">Agent Reasoning · live</span>
        <span className="meta flex items-center gap-1">
          <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--color-healthy)]" />
          stream
        </span>
      </div>
      <div
        ref={scrollRef}
        className="feed flex-1 overflow-y-auto px-3 py-2 font-mono text-xs leading-relaxed"
        style={{ maxHeight: "46vh" }}
      >
        {lines.length === 0 && (
          <p className="text-[var(--color-slate)]">
            Waiting for agent activity — run a scan, simulate an attack, or heal.
          </p>
        )}
        {lines.map((l) => (
          <Line key={l._id} line={l} />
        ))}
      </div>
    </div>
  );
}

function Line({ line }) {
  const color = AGENT_COLOR[line.agent] || "#9aa0aa";
  const critical = line.severity === "critical";
  const glyph = PHASE_GLYPH[line.phase] || "·";
  return (
    <div className={`flex gap-2 py-0.5 ${critical ? "text-[var(--color-critical)]" : ""}`}>
      <span className="w-28 shrink-0 uppercase tracking-wide" style={{ color }}>
        {line.agent}
      </span>
      <span className="w-4 shrink-0 opacity-70">{glyph}</span>
      <span className={critical ? "font-bold" : "text-[var(--color-ink)]/90"}>
        {line.text}
      </span>
    </div>
  );
}
