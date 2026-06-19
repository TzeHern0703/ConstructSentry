import { Sparkles } from "lucide-react";

// Shows the agents' LLM-generated analysis (cyber + carbon) so the generative-AI
// output is visible in the demo, not hidden behind the deterministic feed.
// Lightly renders the **bold** / `code` markdown Gemini tends to emit.
export default function AiSummary({ cyber, carbon, provider }) {
  const live = provider && !provider.startsWith("offline");
  return (
    <div className="border border-white/10 bg-[var(--color-panel)]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="meta flex items-center gap-1.5">
          <Sparkles size={13} /> AI Analysis
        </span>
        <span className="meta" style={{ color: live ? "var(--color-healthy)" : undefined }}>
          {provider || "—"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
        <Block label="Security" color="#5BA8FF" text={cyber} />
        <Block label="Carbon" color="#1FB57A" text={carbon} />
      </div>
    </div>
  );
}

function Block({ label, color, text }) {
  return (
    <div>
      <div className="meta mb-1" style={{ color }}>
        {label}
      </div>
      <div className="text-xs leading-relaxed text-[var(--color-ink)]/85">
        {text ? <Markdown text={text} /> : <span className="text-[var(--color-slate)]">Run a scan to generate analysis.</span>}
      </div>
    </div>
  );
}

// Minimal inline markdown: **bold**, `code`, and line breaks. No dependency.
function Markdown({ text }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => (
        <p key={i} className={line.trim() === "" ? "h-2" : "mb-1"}>
          {renderInline(line)}
        </p>
      ))}
    </>
  );
}

function renderInline(line) {
  // Split on **bold** and `code`, keeping delimiters.
  const parts = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) {
      return (
        <strong key={i} className="font-bold text-[var(--color-ink)]">
          {p.slice(2, -2)}
        </strong>
      );
    }
    if (p.startsWith("`") && p.endsWith("`")) {
      return (
        <code key={i} className="font-mono text-[0.7rem] text-[var(--color-ink)]/90">
          {p.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{p}</span>;
  });
}
