import { Activity, AlertTriangle, ShieldCheck, RotateCcw, FileText, Bot } from "lucide-react";

// Three buttons drive the live demo (FRONTEND_SPEC component 7): Run Scan,
// Simulate Attack, Heal. Rectangular, thin border, uppercase mono labels —
// no rounded pills (Section 4 motion/typography). Reset is a small secondary
// control for re-running the demo.
export default function ControlBar({ onScan, onAttack, onHeal, onReset, onReport, onAutopilot, autopilot, busy, status }) {
  const critical = status === "CRITICAL";
  return (
    <div className="flex items-stretch gap-3 border border-white/10 bg-[var(--color-panel)] p-3">
      <Button
        label="Run Scan"
        icon={Activity}
        onClick={onScan}
        disabled={busy}
        accent="var(--color-ink)"
      />
      <Button
        label="Simulate Attack"
        icon={AlertTriangle}
        onClick={onAttack}
        disabled={busy || critical}
        accent="var(--color-critical)"
      />
      <Button
        label="Heal"
        icon={ShieldCheck}
        onClick={onHeal}
        disabled={busy || !critical}
        accent="var(--color-healthy)"
      />
      <button
        onClick={() => onAutopilot?.(!autopilot)}
        className="flex items-center justify-center gap-2 border px-4 py-3 uppercase tracking-wider transition-all duration-100 active:translate-y-px"
        style={
          autopilot
            ? { background: "#C77DFF", color: "#000", borderColor: "#C77DFF" }
            : { color: "#C77DFF", borderColor: "#C77DFF" }
        }
        title="Let the agent scale workloads autonomously"
      >
        <Bot size={16} />
        <span className="font-mono text-xs font-bold">
          Autopilot {autopilot ? "ON" : "OFF"}
        </span>
      </button>
      <div className="flex-1" />
      <Button
        label="AI Report"
        icon={FileText}
        onClick={onReport}
        disabled={false}
        accent="#C77DFF"
        small
      />
      <Button
        label="Reset"
        icon={RotateCcw}
        onClick={onReset}
        disabled={busy}
        accent="var(--color-slate)"
        small
      />
    </div>
  );
}

function Button({ label, icon: Icon, onClick, disabled, accent, small }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{ borderColor: disabled ? "rgba(255,255,255,0.12)" : accent, color: disabled ? "var(--color-slate)" : accent }}
      className={`group flex items-center justify-center gap-2 border bg-transparent uppercase tracking-wider transition-all duration-100 hover:enabled:bg-white/5 active:enabled:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 ${
        small ? "px-3 py-2" : "flex-1 px-4 py-3"
      }`}
    >
      <Icon size={small ? 14 : 16} />
      <span className="font-mono text-xs font-bold">{label}</span>
    </button>
  );
}
