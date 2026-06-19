import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { HEALTHY, CRITICAL } from "../theme";
import AnimatedNumber from "./AnimatedNumber";

// Fleet carbon over time (FRONTEND_SPEC component 4). The y-axis auto-zooms to
// the data range so the attack step-up reads as a pronounced spike, and the
// whole area turns red while the system is CRITICAL. Numbers are the real
// computed fleet totals — not hardcoded.
export default function CarbonChart({ data, status }) {
  const critical = status === "CRITICAL";
  const color = critical ? CRITICAL : HEALTHY;
  const latest = data?.length ? data[data.length - 1].carbon : 0;

  return (
    <div className="flex min-h-44 flex-col border border-white/10 bg-[var(--color-panel)] p-3">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="meta">Fleet carbon · kg CO2e/mo</span>
        <AnimatedNumber
          value={latest}
          duration={400}
          className="font-display text-lg font-black tabular-nums"
          style={{ color }}
        />
      </div>
      <div className="flex-1">
        <ResponsiveContainer width="100%" height="100%" minHeight={120}>
          <AreaChart data={data} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="carbonFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.55} />
                <stop offset="100%" stopColor={color} stopOpacity={0.03} />
              </linearGradient>
            </defs>
            <XAxis dataKey="t" hide />
            <YAxis
              hide
              domain={[
                (min) => Math.floor(min * 0.9),
                (max) => Math.ceil(max * 1.05),
              ]}
            />
            <Tooltip
              contentStyle={{
                background: "#0b0b0f",
                border: "1px solid #2a2a33",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
              }}
              labelFormatter={() => ""}
              formatter={(v) => [`${Math.round(v)} kg`, "carbon"]}
            />
            <Area
              type="monotone"
              dataKey="carbon"
              stroke={color}
              strokeWidth={2}
              fill="url(#carbonFill)"
              isAnimationActive={true}
              animationDuration={350}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
