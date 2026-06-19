import { ShieldCheck, ShieldAlert, X } from "lucide-react";

// The HEALED-state report card: slides up after remediation. Honors the
// verification result — a partial heal that leaves the miner running shows as
// INCOMPLETE (red), not a green success.
export default function FinalReport({ report, onClose }) {
  if (!report) return null;
  const ok = report.verified !== false;
  const color = ok ? "var(--color-healthy)" : "var(--color-critical)";
  const Icon = ok ? ShieldCheck : ShieldAlert;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-28 z-50 flex justify-center px-6">
      <div
        className="report-card pointer-events-auto relative w-full max-w-2xl border-2 bg-[var(--color-panel)] p-5 shadow-2xl"
        style={{ borderColor: color }}
      >
        <button
          onClick={onClose}
          className="absolute right-3 top-3 text-[var(--color-slate)] hover:text-[var(--color-ink)]"
          aria-label="dismiss"
        >
          <X size={16} />
        </button>
        <div className="flex items-center gap-2" style={{ color }}>
          <Icon size={18} />
          <span className="meta" style={{ color }}>
            {ok ? "Threat neutralized · verified" : "Remediation incomplete · verify failed"}
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-4">
          <Stat
            value={`$${(report.cost_avoided_usd ?? 0).toLocaleString()}/mo`}
            label="cloud cost reclaimed"
            color={color}
          />
          <Stat
            value={`${report.carbon_prevented_kg ?? 0} kg`}
            label="CO2e/mo prevented"
            color={color}
          />
        </div>

        <p className="mt-3 text-xs leading-snug text-[var(--color-ink)]/80">
          {report.headline}
        </p>
      </div>
    </div>
  );
}

function Stat({ value, label, color }) {
  return (
    <div>
      <div
        className="font-display text-3xl font-black leading-none"
        style={{ color }}
      >
        {value}
      </div>
      <div className="meta mt-1">{label}</div>
    </div>
  );
}
