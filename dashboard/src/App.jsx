import { useEffect, useState } from "react";
import {
  getSummary,
  getState,
  getFindings,
  runScan,
  runAttack,
  runRemediate,
  runReset,
  applyAction,
} from "./api";
import { moodColor } from "./theme";
import SummaryRow from "./components/SummaryRow";
import ServerGrid from "./components/ServerGrid";
import RoutingMap from "./components/RoutingMap";
import CarbonChart from "./components/CarbonChart";
import ControlBar from "./components/ControlBar";
import AgentReasoningFeed from "./components/AgentReasoningFeed";
import IncidentList from "./components/IncidentList";
import RemediationModal from "./components/RemediationModal";
import ReportModal from "./components/ReportModal";

const MAX_POINTS = 45;
const HEALED_WINDOW_MS = 14000;

export default function App() {
  const [summary, setSummary] = useState(null);
  const [state, setState] = useState(null);
  const [findings, setFindings] = useState(null);
  const [carbonHistory, setCarbonHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // HEALED is a transient frontend-only state shown right after remediation.
  const [healReport, setHealReport] = useState(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [view, setView] = useState("fleet"); // "fleet" | "map"

  // Poll summary + state every 2s (FRONTEND_SPEC Section 3).
  useEffect(() => {
    let alive = true;
    async function poll() {
      try {
        const [s, st, f] = await Promise.all([
          getSummary(),
          getState(),
          getFindings(),
        ]);
        if (!alive) return;
        setSummary(s);
        setState(st);
        setFindings(f);
        setCarbonHistory((prev) =>
          [...prev, { t: Date.now(), carbon: s.total_carbon_kg }].slice(-MAX_POINTS)
        );
        setError(null);
      } catch (e) {
        if (alive) setError(e.message);
      }
    }
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Pull fresh summary + state immediately after an action (don't wait for the
  // next 2s tick).
  async function refresh() {
    const [s, st, f] = await Promise.all([
      getSummary(),
      getState(),
      getFindings(),
    ]);
    setSummary(s);
    setState(st);
    setFindings(f);
    setCarbonHistory((prev) =>
      [...prev, { t: Date.now(), carbon: s.total_carbon_kg }].slice(-MAX_POINTS)
    );
  }

  function withBusy(action) {
    return async () => {
      if (busy) return;
      setBusy(true);
      setError(null);
      try {
        await action();
        await refresh();
      } catch (e) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    };
  }

  const onApply = (serverId, type) => withBusy(() => applyAction(serverId, type))();

  const onScan = withBusy(async () => {
    setHealReport(null);
    await runScan();
  });
  const onAttack = withBusy(async () => {
    setHealReport(null);
    await runAttack();
  });
  const onReset = withBusy(async () => {
    setHealReport(null);
    await runReset();
  });

  // Heal is special: it triggers the transient HEALED state + report card.
  async function onHeal() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await runRemediate();
      await refresh();
      setHealReport(resp.report);
      setTimeout(() => setHealReport(null), HEALED_WINDOW_MS);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const status = summary?.system_status ?? "…";
  // HEALED overrides the (now HEALTHY) backend status while the report shows.
  const mood = healReport ? "HEALED" : status;
  const moodHex = moodColor(mood === "HEALED" ? "HEALTHY" : mood);

  const stateClass =
    mood === "CRITICAL" ? "state-critical" : mood === "HEALED" ? "state-healed" : "";

  return (
    <div className={`relative flex min-h-full flex-col ${stateClass}`}>
      <Header status={mood} mood={moodHex} critical={mood === "CRITICAL"} source={summary?.intensity_source} />

      {error && (
        <p className="meta px-6 py-2 text-[var(--color-critical)]">
          API error: {error} — is uvicorn running on :8000?
        </p>
      )}

      <RemediationModal report={healReport} onClose={() => setHealReport(null)} />
      <ReportModal
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        summary={summary}
        findings={findings}
      />

      <main className="grid flex-1 grid-cols-1 gap-4 p-6 lg:grid-cols-5">
        {/* LEFT 60% */}
        <section className="flex flex-col gap-4 lg:col-span-3">
          <SummaryRow summary={summary} />
          <div>
            <div className="mb-2 flex gap-1">
              {["fleet", "map"].map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className="meta border px-2 py-1 transition-colors"
                  style={
                    view === v
                      ? { color: "var(--color-ink)", borderColor: "var(--color-ink)" }
                      : { color: "var(--color-slate)", borderColor: "rgba(255,255,255,0.12)" }
                  }
                >
                  {v === "fleet" ? "Fleet" : "Carbon Map"}
                </button>
              ))}
            </div>
            {view === "fleet" ? <ServerGrid servers={state?.servers} /> : <RoutingMap />}
          </div>
          <CarbonChart data={carbonHistory} status={status} />
        </section>

        {/* RIGHT 40% */}
        <section className="flex flex-col gap-4 lg:col-span-2">
          <AgentReasoningFeed />
          <IncidentList
            incidents={findings?.incidents}
            report={findings?.report}
            onApply={onApply}
            busy={busy}
          />
        </section>
      </main>

      <div className="m-6 mt-0">
        <ControlBar
          onScan={onScan}
          onAttack={onAttack}
          onHeal={onHeal}
          onReset={onReset}
          onReport={() => setReportOpen(true)}
          busy={busy}
          status={status}
        />
      </div>
    </div>
  );
}

function Header({ status, mood, critical, source }) {
  return (
    <header className="flex items-center justify-between border-b border-white/10 px-6 py-4">
      <div className="flex items-baseline gap-3">
        <h1 className="font-display text-2xl font-black tracking-tight">
          ConstructSentry
        </h1>
        <span className="meta hidden md:inline">
          Simulated cloud · detection &amp; carbon data are real
          {source ? ` · ${source}` : ""}
        </span>
      </div>
      <div className="flex items-center gap-4">
        <Clock />
        <span
          className={`meta border px-3 py-1 ${critical ? "pulse-critical" : ""}`}
          style={{ color: mood, borderColor: mood }}
        >
          ● {status}
        </span>
      </div>
    </header>
  );
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="meta hidden tabular-nums sm:inline">
      {now.toLocaleTimeString([], { hour12: false })}
    </span>
  );
}

