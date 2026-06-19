import { statusDot, CRITICAL } from "../theme";

// One card per server: name, role, region, CPU%, status dot. A compromised
// server (status critical) flashes red during the attack phase
// (FRONTEND_SPEC component 3).
export default function ServerGrid({ servers }) {
  if (!servers) return null;
  return (
    <div>
      <p className="meta mb-2">Fleet · {servers.length} nodes</p>
      <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
        {servers.map((s) => (
          <ServerCard key={s.id} server={s} />
        ))}
      </div>
    </div>
  );
}

function ServerCard({ server }) {
  const critical = server.status === "critical";
  return (
    <div
      className={`border bg-[var(--color-panel)] p-3 transition-colors ${
        critical ? "flash-red" : "border-white/10"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="truncate font-display text-sm font-semibold">
          {server.id}
        </span>
        <span
          className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ background: statusDot(server.status) }}
        />
      </div>
      <div className="meta mt-1 truncate">{server.role}</div>
      <div className="meta mt-2 flex justify-between">
        <span>{server.region}</span>
        <span style={{ color: server.cpu_utilization > 80 ? CRITICAL : undefined }}>
          CPU {server.cpu_utilization}%
        </span>
      </div>
      {critical && (
        <div className="meta mt-2 font-bold text-[var(--color-critical)]">
          ⚠ Compromised
        </div>
      )}
    </div>
  );
}
