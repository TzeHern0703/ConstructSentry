import { severityColor } from "../theme";

// Correlated incidents, ranked by severity (FRONTEND_SPEC component 6). Each
// card shows the compound finding (security + carbon) and the unified
// recommendation with numbers. Compound incidents get an explicit
// "🔗 SECURITY + CARBON" badge — the whole "1 fix = 3 wins" pitch.
export default function IncidentList({ incidents, report }) {
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
          <IncidentCard key={inc.server_id} inc={inc} />
        ))}
      </div>
    </div>
  );
}

function IncidentCard({ inc }) {
  const color = severityColor(inc.severity);
  const savings = inc.monthly_savings_usd;
  const carbon = inc.carbon_prevented_kg;

  return (
    <div
      className="border-l-2 bg-black/30 p-3"
      style={{ borderColor: color }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-sm font-bold">{inc.server_id}</span>
        <span className="meta" style={{ color }}>
          {inc.category_label}
        </span>
        {inc.is_compound && (
          <span className="meta bg-[var(--color-critical)] px-1.5 py-0.5 font-bold text-black">
            🔗 SECURITY + CARBON
          </span>
        )}
      </div>

      <p className="mt-2 text-xs leading-snug text-[var(--color-ink)]/85">
        {inc.action}
      </p>

      {(savings > 0 || carbon > 0) && (
        <div className="mt-2 flex gap-4">
          {savings > 0 && (
            <Metric value={`$${savings.toLocaleString()}/mo`} label="saved" />
          )}
          {carbon > 0 && (
            <Metric value={`${carbon} kg`} label="CO2e prevented" />
          )}
        </div>
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
