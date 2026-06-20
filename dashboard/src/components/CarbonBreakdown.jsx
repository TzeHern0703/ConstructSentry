import { useEffect, useState } from "react";
import { Flame, Leaf, AlertTriangle } from "lucide-react";
import { getCarbon } from "../api";

// Identifies carbon-intensive / inefficient workloads and shows WHY: the carbon
// bar, utilization, wasted (idle) carbon, and the drivers (oversized instance /
// dirty grid / replicas / near-idle / cooling). Directly answers the challenge.
export default function CarbonBreakdown() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    const tick = () => getCarbon().then((d) => alive && setData(d)).catch(() => {});
    tick();
    const id = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!data) return <div className="meta p-3">Loading…</div>;
  const max = Math.max(...data.workloads.map((w) => w.carbon_kg), 1);

  return (
    <div>
      <p className="meta mb-2">
        Carbon by workload · {Math.round(data.total_carbon_kg)} kg/mo ·{" "}
        <span className="text-[var(--color-critical)]">{Math.round(data.total_wasted_kg)} kg wasted on idle</span>
      </p>
      <div className="space-y-1.5">
        {data.workloads.map((w) => (
          <Row key={w.server_id} w={w} max={max} />
        ))}
      </div>
    </div>
  );
}

function Row({ w, max }) {
  const color = w.intensive ? "#FF2D2D" : w.inefficient ? "#E0A106" : "#1FB57A";
  const Icon = w.intensive ? Flame : w.inefficient ? AlertTriangle : Leaf;
  const tag = w.intensive ? "carbon-intensive" : w.inefficient ? "inefficient" : "efficient";
  const widthPct = Math.max(3, (w.carbon_kg / max) * 100);
  const wastedPct = w.carbon_kg ? (w.wasted_kg / w.carbon_kg) * widthPct : 0;

  return (
    <div className="border border-white/10 bg-black/30 p-2">
      <div className="flex items-center justify-between">
        <span className="meta flex items-center gap-1" style={{ color }}>
          <Icon size={11} /> {w.server_id}
        </span>
        <span className="meta tabular-nums" style={{ color }}>
          {Math.round(w.carbon_kg)} kg · {w.util_pct}% util
        </span>
      </div>
      {/* carbon bar; the amber overlay = carbon wasted on idle capacity */}
      <div className="relative mt-1 h-2 w-full bg-white/5">
        <div className="h-full" style={{ width: `${widthPct}%`, background: color }} />
        <div className="absolute top-0 h-full bg-[var(--color-critical)]/40"
             style={{ width: `${wastedPct}%` }} title="wasted on idle" />
      </div>
      <div className="meta mt-1 flex flex-wrap items-center gap-1.5 normal-case tracking-normal">
        <span style={{ color }}>{tag}</span>
        {w.drivers.length > 0 && (
          <span className="text-[var(--color-ink)]/55">· {w.drivers.join(" · ")}</span>
        )}
        {w.wasted_kg > 5 && (
          <span className="text-[var(--color-critical)]">· {w.wasted_kg} kg idle waste</span>
        )}
      </div>
    </div>
  );
}
