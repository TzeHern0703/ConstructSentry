import { useEffect, useState } from "react";
import { Lock, Leaf } from "lucide-react";
import { getRegions } from "../api";

// Workload-routing visualization: region lanes ordered cleanest-grid first,
// coloured by live carbon intensity, with each server as a chip in its region.
// Makes the abstract "route to a greener grid / time-shift in place" story
// concrete — you can see which workloads sit on dirty grids and where the
// clean capacity is. Residency-locked workloads are marked 🔒 (can't move).
export default function RoutingMap() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    const tick = () => getRegions().then((d) => alive && setData(d)).catch(() => {});
    tick();
    const id = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!data) return <div className="meta p-3">Loading regions…</div>;

  const max = Math.max(...data.regions.map((r) => r.intensity), 1);

  return (
    <div>
      <p className="meta mb-2">
        Carbon by region · cleanest first · greenest ={" "}
        <span className="text-[var(--color-healthy)]">{data.greenest}</span> (route target)
      </p>
      <div className="space-y-1.5">
        {data.regions.map((r) => (
          <Lane key={r.region} r={r} max={max} greenest={r.region === data.greenest} />
        ))}
      </div>
    </div>
  );
}

function intensityColor(v) {
  if (v <= 150) return "#1FB57A";   // clean
  if (v >= 400) return "#FF2D2D";   // dirty
  return "#E0A106";                 // mid
}

function Lane({ r, max, greenest }) {
  const color = intensityColor(r.intensity);
  const widthPct = Math.max(8, (r.intensity / max) * 100);
  return (
    <div className="border border-white/10 bg-black/30 p-2">
      <div className="flex items-center justify-between">
        <span className="meta flex items-center gap-1" style={{ color }}>
          {greenest && <Leaf size={11} />}
          {r.region}
        </span>
        <span className="meta tabular-nums" style={{ color }}>
          {Math.round(r.intensity)} gCO₂/kWh · {r.source}
        </span>
      </div>
      {/* intensity bar */}
      <div className="mt-1 h-1.5 w-full bg-white/5">
        <div className="h-full" style={{ width: `${widthPct}%`, background: color }} />
      </div>
      {/* server chips */}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {r.servers.map((s) => (
          <span
            key={s.id}
            className="meta flex items-center gap-1 border px-1.5 py-0.5 normal-case tracking-normal"
            style={{
              borderColor: s.status === "critical" ? "#FF2D2D" : "rgba(255,255,255,0.15)",
              color: s.status === "critical" ? "#FF2D2D" : undefined,
            }}
            title={`${s.id} · CPU ${s.cpu}%${s.residency_locked ? " · residency-locked" : ""}`}
          >
            {s.residency_locked && <Lock size={9} />}
            {s.id}
          </span>
        ))}
      </div>
    </div>
  );
}
