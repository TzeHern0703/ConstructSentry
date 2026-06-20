import { ShieldAlert, Check, X } from "lucide-react";

// Human-in-the-loop approval: before healing, the agent LISTS the problems it
// found and the remediation it proposes, and asks the operator to approve —
// like a real SOC runbook, not a silent auto-fix.
const PROPOSED_STEPS = [
  ["Network-isolate host", "close SSH / port 22 — cut the attacker's path"],
  ["Terminate unauthorized process", "kill the mining daemon → CPU/GPU back to normal"],
  ["Rotate credentials", "revoke sessions, reset keys"],
  ["Re-scan & verify", "confirm the host is clean before declaring resolved"],
];

export default function HealPlanModal({ incidents, onApprove, onCancel, busy }) {
  const hosts = (incidents ?? []).filter((i) => i.category === "compromised_host");
  if (!hosts.length) return null;

  const totalCost = hosts.reduce((a, h) => a + (h.monthly_savings_usd || 0), 0);
  const totalCarbon = hosts.reduce((a, h) => a + (h.carbon_prevented_kg || 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/70 p-6">
      <div className="report-card my-auto w-full max-w-2xl border-2 border-[var(--color-critical)] bg-[var(--color-panel)]">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <span className="flex items-center gap-2 font-display font-bold text-[var(--color-critical)]">
            <ShieldAlert size={16} /> Heal plan — approval required
          </span>
          <button onClick={onCancel} className="text-[var(--color-slate)] hover:text-[var(--color-ink)]">
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto px-5 py-4">
          <p className="meta normal-case tracking-normal text-[var(--color-ink)]/80">
            The agent detected {hosts.length} compromised host
            {hosts.length > 1 ? "s" : ""}. Review the findings and the proposed
            remediation, then approve.
          </p>

          {hosts.map((h) => {
            const findings = [...(h.cyber_findings ?? []), ...(h.carbon_findings ?? [])];
            return (
              <div key={h.server_id} className="border-l-2 border-[var(--color-critical)] bg-black/30 p-3">
                <div className="font-display text-sm font-bold">{h.server_id}</div>

                <div className="meta mt-2">Discovered ({findings.length})</div>
                <ul className="mt-1 space-y-0.5">
                  {findings.map((f, i) => (
                    <li key={i} className="text-xs text-[var(--color-ink)]/85">
                      <span
                        className="mr-1 font-mono"
                        style={{ color: f.severity === "critical" ? "#FF2D2D" : "#E0A106" }}
                      >
                        [{f.type}]
                      </span>
                      {f.evidence}
                    </li>
                  ))}
                </ul>

                <div className="meta mt-3">Proposed remediation</div>
                <ol className="mt-1 space-y-0.5">
                  {PROPOSED_STEPS.map(([label, detail], i) => (
                    <li key={i} className="text-xs text-[var(--color-ink)]/85">
                      <span className="font-bold">{i + 1}. {label}</span>
                      <span className="text-[var(--color-ink)]/55"> — {detail}</span>
                    </li>
                  ))}
                </ol>

                <div className="meta mt-3 normal-case tracking-normal text-[var(--color-healthy)]">
                  Projected: security restored + ${(h.monthly_savings_usd || 0).toLocaleString()}/mo
                  + {h.carbon_prevented_kg || 0} kg CO₂e/mo
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-white/10 px-5 py-3">
          <span className="meta">
            Total: ${totalCost.toLocaleString()}/mo · {Math.round(totalCarbon)} kg CO₂e/mo
          </span>
          <div className="flex gap-2">
            <button
              onClick={onCancel}
              className="meta border border-white/20 px-3 py-2 hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              onClick={onApprove}
              disabled={busy}
              className="meta flex items-center gap-1.5 border border-[var(--color-healthy)] bg-[var(--color-healthy)] px-3 py-2 font-bold text-black disabled:opacity-50"
            >
              <Check size={14} /> Approve &amp; Heal ▸
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
