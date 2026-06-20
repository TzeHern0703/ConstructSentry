import { ArrowDown, ArrowUp, Check } from "lucide-react";

// Latency-vs-SLO benchmark for horizontally-scalable workloads. Shows the agent
// is tracking real performance (p95 latency, replicas) and right-sizing to the
// SLO — the operational basis for carbon-aware autoscaling.
export default function ScalingBench({ servers, onApply, busy }) {
  const scalable = (servers ?? []).filter((s) => s.latency_slo_ms);
  if (!scalable.length) return <div className="meta p-3">No scalable workloads.</div>;

  return (
    <div>
      <p className="meta mb-2">Latency vs SLO · replicas right-sized to the SLO</p>
      <div className="space-y-1.5">
        {scalable.map((s) => (
          <Row key={s.id} s={s} onApply={onApply} busy={busy} />
        ))}
      </div>
    </div>
  );
}

function Row({ s, onApply, busy }) {
  const lat = s.latency_p95_ms;
  const slo = s.latency_slo_ms;
  const replicas = s.replicas ?? 1;
  const breach = lat > slo;
  // Min replicas that keep latency within SLO (same model as the backend).
  const target = Math.max(1, Math.ceil((lat * replicas) / slo));
  const dir = target > replicas ? "up" : target < replicas ? "down" : "ok";

  const color = breach ? "#FF2D2D" : "#1FB57A";
  // bar: latency as % of SLO (cap display at 130%)
  const pct = Math.min(130, (lat / slo) * 100);

  return (
    <div className="border border-white/10 bg-black/30 p-2">
      <div className="flex items-center justify-between">
        <span className="meta">{s.id}</span>
        <span className="meta tabular-nums" style={{ color }}>
          {lat}ms / {slo}ms SLO · {replicas}×
        </span>
      </div>
      {/* latency vs SLO bar; SLO marked at 100% */}
      <div className="relative mt-1 h-2 w-full bg-white/5">
        <div className="h-full" style={{ width: `${(pct / 130) * 100}%`, background: color }} />
        {/* SLO marker at 100/130 of width */}
        <div
          className="absolute top-[-2px] h-3 w-px bg-white/60"
          style={{ left: `${(100 / 130) * 100}%` }}
          title="SLO"
        />
      </div>
      <div className="meta mt-1 flex items-center gap-2 normal-case tracking-normal">
        {dir === "ok" && <span className="flex items-center gap-1"><Check size={11} color="#1FB57A" /> optimal — {replicas} replicas</span>}
        {dir === "down" && (
          <span style={{ color: "#1FB57A" }} className="flex items-center gap-1">
            <ArrowDown size={11} /> scale {replicas}→{target} (carbon saved, still within SLO)
          </span>
        )}
        {dir === "up" && (
          <span style={{ color: "#E0A106" }} className="flex items-center gap-1">
            <ArrowUp size={11} /> scale {replicas}→{target} (restore SLO)
          </span>
        )}
        {dir !== "ok" && onApply && (
          <button
            onClick={() => onApply(s.id, dir === "up" ? "scale_up" : "scale_down")}
            disabled={busy}
            className="ml-auto border border-white/40 px-2 py-0.5 font-bold uppercase tracking-wider hover:enabled:bg-white/10 disabled:opacity-40"
          >
            Apply ▸
          </button>
        )}
      </div>
    </div>
  );
}
