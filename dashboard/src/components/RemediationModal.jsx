import { useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert, Check, Loader2, X } from "lucide-react";

// Makes the heal VISIBLE: instead of an instant jump, it reveals each
// remediation action one at a time with its concrete effect (CPU 95%→18%,
// failed logins 450→0, …), then the verify result and the savings. So you can
// actually watch what the fix did.
const STEP_DELAY_MS = 850;

export default function RemediationModal({ report, onClose }) {
  const actions = report?.actions ?? [];
  const [shown, setShown] = useState(0);

  // Reveal actions one by one whenever a new report opens.
  useEffect(() => {
    if (!report) return;
    setShown(0);
    const timers = actions.map((_, i) =>
      setTimeout(() => setShown((n) => Math.max(n, i + 1)), STEP_DELAY_MS * (i + 1))
    );
    return () => timers.forEach(clearTimeout);
  }, [report]);

  if (!report) return null;

  const done = shown >= actions.length;
  const ok = report.verified !== false;
  const color = ok ? "var(--color-healthy)" : "var(--color-critical)";
  const Icon = ok ? ShieldCheck : ShieldAlert;
  const hb = report.host_before ?? {};
  const ha = report.host_after ?? {};

  return (
    <div className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/70 p-6">
      <div className="report-card my-auto w-full max-w-xl border-2 bg-[var(--color-panel)]" style={{ borderColor: color }}>
        {/* header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <span className="font-display font-bold">Remediation · {report.target}</span>
          <button onClick={onClose} className="text-[var(--color-slate)] hover:text-[var(--color-ink)]">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-5 py-4">
          {/* host before */}
          <div className="grid grid-cols-3 gap-2">
            <Mini label="CPU" value={`${hb.cpu}%`} bad />
            <Mini label="Failed logins" value={hb.failed_logins} bad />
            <Mini label="Carbon kg/mo" value={Math.round(hb.carbon_kg ?? 0)} bad />
          </div>

          {/* animated action list */}
          <div className="space-y-2">
            {actions.map((a, i) => {
              const visible = i < shown;
              const isVerify = a.step === "verify";
              const stepOk = !isVerify || a.ok;
              return (
                <div
                  key={i}
                  className={`flex items-start gap-3 border border-white/10 bg-black/30 px-3 py-2 transition-all duration-300 ${
                    visible ? "opacity-100" : "opacity-25"
                  }`}
                >
                  <span className="mt-0.5">
                    {!visible ? (
                      <Loader2 size={15} className="animate-spin text-[var(--color-slate)]" />
                    ) : isVerify ? (
                      stepOk ? <ShieldCheck size={15} color="var(--color-healthy)" />
                             : <ShieldAlert size={15} color="var(--color-critical)" />
                    ) : (
                      <Check size={15} color="var(--color-healthy)" />
                    )}
                  </span>
                  <div className="min-w-0">
                    <div className="font-display text-sm font-semibold">{a.label}</div>
                    {visible && <div className="meta normal-case tracking-normal mt-0.5">{a.detail}</div>}
                  </div>
                </div>
              );
            })}
          </div>

          {/* result — appears after all steps revealed */}
          {done && (
            <div className="report-card border-t border-white/10 pt-4" style={{ color }}>
              <div className="flex items-center gap-2">
                <Icon size={18} />
                <span className="meta" style={{ color }}>
                  {ok ? "Verified · threat neutralized" : "Remediation incomplete · verify failed"}
                </span>
              </div>
              {ok && (
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <Mini label="cloud cost reclaimed" value={`$${(report.cost_avoided_usd ?? 0).toLocaleString()}/mo`} />
                  <Mini label="CO₂e prevented" value={`${report.carbon_prevented_kg ?? 0} kg/mo`} />
                </div>
              )}
              <p className="mt-2 text-xs leading-snug text-[var(--color-ink)]/80">{report.headline}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Mini({ label, value, bad }) {
  return (
    <div className="border border-white/10 bg-black/30 px-3 py-2">
      <div
        className="font-display text-lg font-black leading-none tabular-nums"
        style={{ color: bad ? "var(--color-critical)" : "var(--color-healthy)" }}
      >
        {value}
      </div>
      <div className="meta mt-1">{label}</div>
    </div>
  );
}
