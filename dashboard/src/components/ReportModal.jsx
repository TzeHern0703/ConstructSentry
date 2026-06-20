import { FileText, Download, X } from "lucide-react";
import { severityColor, moodColor } from "../theme";

// "AI Report" overlay: a clean, exportable incident report that keeps the
// LLM's long-form analysis OUT of the dense live dashboard (so the mission-
// control page stays coherent) while still showing it on demand + as a .md
// download.
export default function ReportModal({ open, onClose, summary, findings }) {
  if (!open) return null;

  const incidents = findings?.incidents ?? [];
  const report = findings?.report ?? {};
  const provider = findings?.provider ?? "—";
  const ts = new Date().toLocaleString();
  const mood = moodColor(summary?.system_status);

  function downloadMd() {
    const md = buildMarkdown({ summary, findings, ts });
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `constructsentry-report-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-center overflow-y-auto bg-black/70 p-6">
      <div className="report-card my-auto w-full max-w-3xl border-2 border-white/15 bg-[var(--color-panel)]">
        {/* header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <div className="flex items-center gap-2">
            <FileText size={16} className="text-[#C77DFF]" />
            <span className="font-display font-bold">AI Incident Report</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={downloadMd}
              className="meta flex items-center gap-1.5 border border-[#C77DFF] px-3 py-1.5 text-[#C77DFF] hover:bg-white/5"
            >
              <Download size={13} /> Download .md
            </button>
            <button onClick={onClose} className="text-[var(--color-slate)] hover:text-[var(--color-ink)]">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="max-h-[78vh] space-y-5 overflow-y-auto px-5 py-4">
          <p className="meta">
            Generated {ts} · {provider} · {summary?.intensity_source} carbon data
          </p>

          {/* snapshot */}
          <div>
            <span
              className="meta border px-2 py-1"
              style={{ color: mood, borderColor: mood }}
            >
              SYSTEM: {summary?.system_status ?? "—"}
            </span>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Snap label="Security" value={`${summary?.security_score ?? "—"}/100`} />
              <Snap label="Carbon kg/mo" value={Math.round(summary?.total_carbon_kg ?? 0)} />
              <Snap label="Cost/mo" value={`$${(summary?.total_cost_usd ?? 0).toLocaleString()}`} />
              <Snap label="Critical" value={summary?.critical_count ?? 0} />
            </div>
          </div>

          {/* AI analysis */}
          <Section title="AI Analysis — Security" color="#5BA8FF">
            <Markdown text={findings?.cyber_narrative} />
          </Section>
          <Section title="AI Analysis — Carbon" color="#1FB57A">
            <Markdown text={findings?.carbon_narrative} />
          </Section>

          {/* incidents */}
          <Section
            title={`Ranked Incidents (${incidents.length} · ${report.compound_count ?? 0} compound)`}
            color="var(--color-ink)"
          >
            <div className="space-y-2">
              {incidents.map((inc, i) => (
                <div
                  key={inc.server_id}
                  className="border-l-2 bg-black/30 p-3"
                  style={{ borderColor: severityColor(inc.severity) }}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-display text-sm font-bold">
                      {i + 1}. {inc.server_id}
                    </span>
                    <span className="meta" style={{ color: severityColor(inc.severity) }}>
                      {inc.category_label}
                    </span>
                    {inc.is_compound && (
                      <span className="meta bg-[var(--color-critical)] px-1.5 py-0.5 font-bold text-black">
                        🔗 SECURITY + CARBON
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-xs text-[var(--color-ink)]/85">{inc.action}</p>
                  <ul className="mt-1.5 space-y-0.5">
                    {inc.wins?.map((w, j) => (
                      <li key={j} className="meta normal-case tracking-normal">· {w}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Section>

          {/* totals */}
          <div className="border border-white/10 bg-black/30 p-3">
            <span className="meta">Potential impact</span>
            <div className="mt-1 font-display text-lg font-black text-[var(--color-healthy)]">
              ${(report.total_monthly_savings_usd ?? 0).toLocaleString()}/mo
              <span className="mx-2 text-[var(--color-slate)]">·</span>
              {report.total_carbon_prevented_kg ?? 0} kg CO₂e/mo recoverable
            </div>
          </div>

          {/* business view — why it matters, where the value is */}
          <BusinessImpact report={report} />
          <Section title="Why this matters (business)" color="var(--color-ink)">
            <ul className="space-y-1">
              <li>🔒 <b>Blueprint &amp; asset IP protected</b> — a compromised host exposes
                project data; correlating it with carbon catches it faster.</li>
              <li>📑 <b>Subcontractor governance</b> — orphaned access from ended
                contracts is a compliance + audit risk, closed automatically.</li>
              <li>💰 <b>Project-cloud margin</b> — recovered spend drops straight to
                the project's bottom line.</li>
              <li>🌱 <b>ESG / sustainability reporting</b> — verifiable CO₂e cuts with
                live grid data, defensible in a sustainability audit.</li>
            </ul>
          </Section>

          <p className="meta">
            Simulated construction-cloud environment · detection logic &amp; carbon
            data are real · attack is a local simulation.
          </p>
        </div>
      </div>
    </div>
  );
}

function BusinessImpact({ report }) {
  const annualUsd = (report.total_monthly_savings_usd ?? 0) * 12;
  const annualKg = (report.total_carbon_prevented_kg ?? 0) * 12;
  const trees = Math.round(annualKg / 21); // a mature tree absorbs ~21 kg CO₂/yr
  const kmDriven = Math.round(annualKg * 6); // ~6 km per kg CO₂ (avg car)
  return (
    <Section title="Business impact (annualized)" color="var(--color-healthy)">
      <div className="grid grid-cols-3 gap-3">
        <Snap label="saved / year" value={`$${annualUsd.toLocaleString()}`} />
        <Snap label="CO₂e / year" value={`${annualKg.toLocaleString()} kg`} />
        <Snap label="≈ trees planted" value={trees.toLocaleString()} />
      </div>
      <p className="meta mt-2 normal-case tracking-normal text-[var(--color-ink)]/60">
        Carbon cut ≈ taking {kmDriven.toLocaleString()} km of driving off the road per year.
      </p>
    </Section>
  );
}

function Snap({ label, value }) {
  return (
    <div className="border border-white/10 bg-black/30 px-3 py-2">
      <div className="font-display text-xl font-black tabular-nums">{value}</div>
      <div className="meta mt-0.5">{label}</div>
    </div>
  );
}

function Section({ title, color, children }) {
  return (
    <div>
      <div className="meta mb-1.5" style={{ color }}>
        {title}
      </div>
      <div className="text-xs leading-relaxed text-[var(--color-ink)]/85">{children}</div>
    </div>
  );
}

// Minimal inline markdown: **bold**, `code`, line breaks. No dependency.
function Markdown({ text }) {
  if (!text) return <span className="text-[var(--color-slate)]">Run a scan to generate analysis.</span>;
  return (
    <>
      {text.split("\n").map((line, i) => (
        <p key={i} className={line.trim() === "" ? "h-2" : "mb-1"}>
          {renderInline(line)}
        </p>
      ))}
    </>
  );
}

function renderInline(line) {
  return line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**"))
      return <strong key={i} className="font-bold text-[var(--color-ink)]">{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`"))
      return <code key={i} className="font-mono text-[0.7rem] text-[var(--color-ink)]/90">{p.slice(1, -1)}</code>;
    return <span key={i}>{p}</span>;
  });
}

// Build the downloadable markdown report.
function buildMarkdown({ summary, findings, ts }) {
  const s = summary ?? {};
  const f = findings ?? {};
  const incidents = f.incidents ?? [];
  const r = f.report ?? {};
  const L = [];
  L.push("# ConstructSentry — AI Incident Report");
  L.push(`_Generated ${ts} · ${f.provider ?? "—"} · ${s.intensity_source ?? "—"} carbon data_`);
  L.push("");
  L.push(`## System status: ${s.system_status ?? "—"}`);
  L.push(`- Security score: ${s.security_score ?? "—"}/100`);
  L.push(`- Total carbon: ${Math.round(s.total_carbon_kg ?? 0)} kg CO2e/mo`);
  L.push(`- Monthly cost: $${(s.total_cost_usd ?? 0).toLocaleString()}`);
  L.push(`- Critical incidents: ${s.critical_count ?? 0}`);
  L.push("");
  L.push("## AI Analysis — Security");
  L.push(f.cyber_narrative ?? "_n/a_");
  L.push("");
  L.push("## AI Analysis — Carbon");
  L.push(f.carbon_narrative ?? "_n/a_");
  L.push("");
  L.push(`## Ranked incidents (${incidents.length} · ${r.compound_count ?? 0} compound)`);
  incidents.forEach((inc, i) => {
    L.push("");
    L.push(`### ${i + 1}. ${inc.server_id} — ${inc.category_label}${inc.is_compound ? " [SECURITY + CARBON]" : ""}`);
    L.push(inc.action ?? "");
    (inc.wins ?? []).forEach((w) => L.push(`- ${w}`));
  });
  L.push("");
  L.push("## Potential impact");
  L.push(`- $${(r.total_monthly_savings_usd ?? 0).toLocaleString()}/mo recoverable`);
  L.push(`- ${r.total_carbon_prevented_kg ?? 0} kg CO2e/mo recoverable`);
  L.push("");
  const annUsd = (r.total_monthly_savings_usd ?? 0) * 12;
  const annKg = (r.total_carbon_prevented_kg ?? 0) * 12;
  L.push("## Business impact (annualized)");
  L.push(`- $${annUsd.toLocaleString()}/year saved`);
  L.push(`- ${annKg.toLocaleString()} kg CO2e/year (~${Math.round(annKg / 21)} trees, ~${Math.round(annKg * 6).toLocaleString()} km driving)`);
  L.push("- Blueprint/asset IP protected · subcontractor access governance · project-cloud margin · ESG reporting");
  L.push("");
  L.push("---");
  L.push("Simulated construction-cloud environment · detection logic & carbon data are real · attack is a local simulation.");
  return L.join("\n");
}
