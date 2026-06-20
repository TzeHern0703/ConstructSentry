import { useState } from "react";
import { severityColor } from "../theme";

const ACTION_COLOR = {
  Terminate: "#FF2D2D",
  Hibernate: "#5BA8FF",
  "Right-size": "#E0A106",
  "Scale down": "#1FB57A",
  "Scale up": "#E0A106",
  Relocate: "#1FB57A",
  "Time-shift": "#1FB57A",
  "Isolate & restore": "#C77DFF",
  "Harden config": "#9aa0aa",
};

// Action types that can be executed in one click.
const EXECUTABLE = ["terminate", "hibernate", "scale_down", "scale_up"];

// Correlated incidents, ranked. Each card shows the compound finding, the
// recommended lifecycle ACTION per workload (terminate / hibernate / right-size
// / route …), and — where the choice changes the result — a toggle so you can
// switch terminate↔hibernate and watch the savings update.
export default function IncidentList({ incidents, report, onApply, busy }) {
  return (
    <div className="flex flex-1 flex-col border border-white/10 bg-[var(--color-panel)]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="meta">Incidents · ranked</span>
        {report && (
          <span className="meta">
            {report.compound_count} compound · ${report.total_monthly_savings_usd?.toLocaleString()}/mo
          </span>
        )}
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-3" style={{ maxHeight: "44vh" }}>
        {(!incidents || incidents.length === 0) && (
          <p className="meta text-[var(--color-slate)]">No incidents.</p>
        )}
        {incidents?.map((inc) => (
          <IncidentCard key={inc.server_id} inc={inc} onApply={onApply} busy={busy} />
        ))}
      </div>
    </div>
  );
}

function IncidentCard({ inc, onApply, busy }) {
  const color = severityColor(inc.severity);
  const options = inc.action_options ?? [];
  const [optIdx, setOptIdx] = useState(0);

  // When toggling terminate↔hibernate, show that option's numbers/action.
  const chosen = options[optIdx];
  const savings = chosen ? chosen.savings_usd : inc.monthly_savings_usd;
  const carbon = chosen ? chosen.carbon_kg : inc.carbon_prevented_kg;
  const action = chosen ? chosen.action : inc.action;
  const actionLabel = chosen ? chosen.label : inc.action_label;
  const actionColor = ACTION_COLOR[actionLabel] || "#9aa0aa";

  return (
    <div className="border-l-2 bg-black/30 p-3" style={{ borderColor: color }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-sm font-bold">{inc.server_id}</span>
        <span className="meta" style={{ color }}>{inc.category_label}</span>
        {inc.is_compound && (
          <span className="meta bg-[var(--color-critical)] px-1.5 py-0.5 font-bold text-black">
            🔗 SECURITY + CARBON
          </span>
        )}
        {/* recommended action chip */}
        <span
          className="meta ml-auto border px-1.5 py-0.5 font-bold"
          style={{ color: actionColor, borderColor: actionColor }}
        >
          {actionLabel}
        </span>
      </div>

      <p className="mt-2 text-xs leading-snug text-[var(--color-ink)]/85">{action}</p>

      {/* terminate ↔ hibernate: compare options, then Apply for real */}
      {options.length > 1 && (
        <div className="mt-2">
          <div className="flex items-center gap-1">
            {options.map((o, i) => (
              <button
                key={o.type}
                onClick={() => setOptIdx(i)}
                className="meta border px-2 py-1 transition-colors"
                style={
                  i === optIdx
                    ? { background: ACTION_COLOR[o.label], color: "#000", borderColor: ACTION_COLOR[o.label] }
                    : { color: "var(--color-slate)", borderColor: "rgba(255,255,255,0.15)" }
                }
              >
                {o.label}
              </button>
            ))}
            <button
              onClick={() => onApply?.(inc.server_id, chosen.type)}
              disabled={busy}
              className="meta ml-auto border border-white/40 px-2 py-1 font-bold hover:enabled:bg-white/10 disabled:opacity-40"
            >
              Apply ▸
            </button>
          </div>
          {chosen?.note && (
            <div className="meta mt-1 normal-case tracking-normal opacity-70">{chosen.note}</div>
          )}
        </div>
      )}

      {(savings > 0 || carbon > 0) && (
        <div className="mt-2 flex items-end gap-4">
          {savings > 0 && <Metric value={`$${savings.toLocaleString()}/mo`} label="saved" />}
          {carbon > 0 && <Metric value={`${carbon} kg`} label="CO2e prevented" />}
        </div>
      )}

      {/* single-click Apply for executable actions without a toggle */}
      {options.length <= 1 && EXECUTABLE.includes(inc.action_type) && (
        <button
          onClick={() => onApply?.(inc.server_id, inc.action_type)}
          disabled={busy}
          className="meta mt-2 border border-white/40 px-2 py-1 font-bold hover:enabled:bg-white/10 disabled:opacity-40"
        >
          Apply {inc.action_label} ▸
        </button>
      )}
    </div>
  );
}

function Metric({ value, label }) {
  return (
    <div>
      <div className="font-display text-base font-black leading-none text-[var(--color-healthy)]">
        {value}
      </div>
      <div className="meta mt-0.5">{label}</div>
    </div>
  );
}
