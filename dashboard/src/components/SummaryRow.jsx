import { HEALTHY, CRITICAL } from "../theme";
import AnimatedNumber from "./AnimatedNumber";

// Three big numbers: Security Score, Total Carbon, Monthly Cost
// (FRONTEND_SPEC component 2). Critical count rides along as a small marker.
export default function SummaryRow({ summary }) {
  if (!summary) return <div className="h-28" />;

  const secColor = summary.security_score < 70 ? CRITICAL : HEALTHY;
  const wasted = summary.recoverable_usd ?? 0;
  const totalK = ((summary.total_cost_usd ?? 0) / 1000).toFixed(1);

  return (
    <div className="grid grid-cols-3 gap-3">
      <Stat
        label="Security Score"
        value={summary.security_score}
        suffix="/100"
        color={secColor}
      />
      <Stat
        label="Carbon · kg CO2e/mo"
        value={Math.round(summary.total_carbon_kg)}
        color={HEALTHY}
      />
      <Stat
        label="Wasted spend · recoverable/mo"
        sub={`of $${totalK}k cloud spend`}
        prefix="$"
        value={wasted}
        color={wasted > 0 ? "#E0A106" : HEALTHY}
      />
    </div>
  );
}

function Stat({ label, value, prefix = "", suffix = "", sub, color }) {
  return (
    <div className="border border-white/10 bg-[var(--color-panel)] px-4 py-3 transition-colors">
      <div
        className="font-display text-4xl font-black leading-none tabular-nums"
        style={{ color }}
      >
        {prefix}
        <AnimatedNumber value={value} />
        <span className="text-xl opacity-60">{suffix}</span>
      </div>
      <div className="meta mt-2">{label}</div>
      {sub && <div className="meta mt-0.5 opacity-60">{sub}</div>}
    </div>
  );
}
