import { ShieldCheck, X } from "lucide-react";

// The HEALED-state report card: slides up after remediation with the savings
// numbers (FRONTEND_SPEC Section 4, "the three states"). Auto-dismisses with
// the healed window; also closable.
export default function FinalReport({ report, onClose }) {
  if (!report) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-28 z-50 flex justify-center px-6">
      <div className="report-card pointer-events-auto relative w-full max-w-2xl border-2 border-[var(--color-healthy)] bg-[var(--color-panel)] p-5 shadow-2xl">
        <button
          onClick={onClose}
          className="absolute right-3 top-3 text-[var(--color-slate)] hover:text-[var(--color-ink)]"
          aria-label="dismiss"
        >
          <X size={16} />
        </button>
        <div className="flex items-center gap-2 text-[var(--color-healthy)]">
          <ShieldCheck size={18} />
          <span className="meta" style={{ color: "var(--color-healthy)" }}>
            Threat neutralized
          </span>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-4">
          <Stat
            value={`$${(report.cost_avoided_usd ?? 0).toLocaleString()}/mo`}
            label="cloud cost reclaimed"
          />
          <Stat
            value={`${report.carbon_prevented_kg ?? 0} kg`}
            label="CO2e/mo prevented"
          />
        </div>

        <p className="mt-3 text-xs leading-snug text-[var(--color-ink)]/80">
          {report.headline}
        </p>
      </div>
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div>
      <div className="font-display text-3xl font-black leading-none text-[var(--color-healthy)]">
        {value}
      </div>
      <div className="meta mt-1">{label}</div>
    </div>
  );
}
