"""api.py — thin FastAPI layer over the ConstructSentry backend.

No business logic here (FRONTEND_SPEC Section 2): each endpoint calls an
existing backend function and returns its result as JSON. The one piece of
real machinery is the SSE broker, which fans the agents' Reason/Act/Observe
``emit`` events out to the dashboard's live feed.

Run:  uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import math
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import attack_simulator
import orchestrator
import remediation
import state_store
import tools

app = FastAPI(title="ConstructSentry API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# SSE broker — fan agent thoughts out to all connected dashboards.
# ===========================================================================

class Broker:
    def __init__(self):
        self.subscribers: set[asyncio.Queue] = set()

    def publish(self, event: dict):
        for q in list(self.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self.subscribers.discard(q)


broker = Broker()


def _make_emit(loop: asyncio.AbstractEventLoop):
    """Build an emit callback safe to call from a worker thread."""
    def emit(event: dict):
        loop.call_soon_threadsafe(broker.publish, event)
    return emit


# ===========================================================================
# Result cache — polling endpoints read the last computed scan so we don't
# re-run agents (and possibly re-bill the LLM) on every 2s poll.
# ===========================================================================

_LAST: dict | None = None

# Agent narratives persist across the cheap monitor sweeps (which have none), so
# the AI-summary panel keeps showing the last real LLM analysis.
_NARRATIVE: dict = {"cyber": None, "carbon": None, "provider": "offline"}


def _refresh(state=None, emit=None) -> dict:
    global _LAST, _NARRATIVE
    state = state or state_store.load_state()
    results = orchestrator.run(state, emit=emit)
    summary = orchestrator.summarize(state, results)
    _LAST = {"results": results, "summary": summary, "ts": time.time(), "state": state}
    _NARRATIVE = {
        "cyber": results["cyber"]["narrative"],
        "carbon": results["carbon"]["narrative"],
        "provider": results["cyber"].get("provider"),
    }
    return _LAST


# --- Continuous monitoring (#1) -------------------------------------------
# A background loop re-scans the environment on a fixed interval — not just when
# the user clicks. It diffs against the previous scan and pushes only changes
# (new / escalated / cleared incidents) plus a heartbeat, so the system does
# real continuous monitoring rather than on-demand snapshots.

MONITOR_INTERVAL_SECONDS = 6
_prev_sig: dict[str, tuple[str, str]] = {}
_SEV_RANK = {"info": 0, "warning": 1, "critical": 2}

# Autopilot: when on, the agent autonomously applies safe scaling actions in the
# monitor loop (no human click) to keep every workload right-sized to its SLO.
_autopilot = False
_tick = 0
_phase: dict[str, float] = {}
LOAD_AMPLITUDE = 0.32  # request volume swings ±32% over time


def _incident_signature(results: dict) -> dict:
    return {
        i["server_id"]: (i["category"], i["severity"])
        for i in results["orchestrator"]["incidents"]
    }


def _apply_load_wave(state, baseline):
    """Drive a live traffic wave: latency = seed_latency × (seed_replicas /
    current_replicas) × loadfactor(t). So real load fluctuates and latency
    responds to BOTH demand and the current replica count — giving the
    autoscaler something to continuously track."""
    global _tick
    for srv in state["servers"]:
        if not srv.get("latency_slo_ms"):
            continue
        bsrv = state_store.get_server(baseline, srv["id"])
        if not bsrv:
            continue
        seed_lat = bsrv["latency_p95_ms"]
        seed_rep = max(1, bsrv.get("replicas", 1))
        ph = _phase.setdefault(srv["id"], (hash(srv["id"]) % 100) / 100 * 6.283)
        loadfactor = 1 + LOAD_AMPLITUDE * math.sin(_tick / 3.0 + ph)
        rep = max(1, srv.get("replicas", 1))
        srv["latency_p95_ms"] = max(5, round(seed_lat * seed_rep / rep * loadfactor))
    _tick += 1


def _autopilot_scale(state):
    """Agent acts on its own: apply safe scale up/down so each workload meets its
    SLO at the fewest replicas. Returns a list of applied action descriptions."""
    applied = []
    for srv in state["servers"]:
        if not srv.get("latency_slo_ms"):
            continue
        finding = tools.check_scaling(srv)
        if not finding:
            continue
        m = finding["metrics"]
        before = srv.get("replicas", 1)
        srv["replicas"] = m["target_replicas"]
        srv["latency_p95_ms"] = m["projected_latency_ms"]
        applied.append(
            f"{srv['id']} {before}→{m['target_replicas']} replicas "
            f"({'↓ headroom' if m['direction'] == 'down' else '↑ SLO breach'}, "
            f"p95 ~{m['projected_latency_ms']}ms)"
        )
    return applied


async def _monitor_loop():
    global _LAST, _prev_sig
    loop = asyncio.get_running_loop()
    baseline = state_store.load_baseline()
    while True:
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
        try:
            def sweep():
                with state_store.transaction():
                    state = state_store.load_state()
                    _apply_load_wave(state, baseline)  # in-memory traffic wave
                    auto = _autopilot_scale(state) if _autopilot else []
                    # Persist only when the agent actually changed capacity — the
                    # ephemeral latency wave doesn't churn the seed file.
                    if auto:
                        state_store.save_state(state)
                results = orchestrator.quick_results(state)
                summary = orchestrator.summarize(state, results)
                return state, results, summary, auto

            state, results, summary, auto = await loop.run_in_executor(None, sweep)
            _LAST = {"results": results, "summary": summary, "ts": time.time(), "state": state}

            for desc in auto:
                broker.publish({"agent": "autopilot", "phase": "act",
                                "text": f"🤖 Autopilot scaled {desc}", "severity": "info"})

            # Heal is an agent skill too: when autonomous, the agent remediates
            # any compromised host itself (isolate → kill → rotate → verify).
            if _autopilot:
                compromised = [i["server_id"] for i in results["orchestrator"]["incidents"]
                               if i["category"] == "compromised_host"]
                if compromised:
                    broker.publish({"agent": "autopilot", "phase": "reason",
                                    "text": f"🤖 Compromised host detected ({', '.join(compromised)}) — auto-healing.",
                                    "severity": "critical"})

                    def heal_all():
                        reps = []
                        for sid in compromised:
                            rep = remediation.remediate(target_id=sid,
                                                        emit=lambda e: broker.publish(e))
                            reps.append({k: v for k, v in rep.items() if k != "state"})
                        return _refresh_fast(), reps

                    last, reps = await loop.run_in_executor(None, heal_all)
                    results, summary, state = last["results"], last["summary"], last["state"]
                    # Broadcast the heal report so the dashboard shows the same
                    # "what was solved" summary card as a manual heal.
                    for rep in reps:
                        broker.publish({"agent": "autopilot", "phase": "heal_done",
                                        "report": rep, "severity": "info",
                                        "text": f"🤖 Autopilot healed {rep['target']} — "
                                                f"{rep['headline'][:70]}"})

            sig = _incident_signature(results)
            for sid, (cat, sev) in sig.items():
                prev = _prev_sig.get(sid)
                if prev is None:
                    broker.publish({"agent": "monitor", "phase": "observe",
                                    "text": f"New incident: {sid} — {cat} ({sev}).",
                                    "severity": sev})
                elif _SEV_RANK.get(sev, 0) > _SEV_RANK.get(prev[1], 0):
                    broker.publish({"agent": "monitor", "phase": "observe",
                                    "text": f"{sid} escalated to {sev} ({cat}).",
                                    "severity": sev})
            for sid in _prev_sig:
                if sid not in sig:
                    broker.publish({"agent": "monitor", "phase": "observe",
                                    "text": f"{sid} cleared — back to nominal.",
                                    "severity": "info"})
            _prev_sig = sig

            mode = "AUTOPILOT" if _autopilot else "monitor"
            broker.publish({
                "agent": "monitor", "phase": "reason",
                "text": (f"{mode} sweep · {len(state['servers'])} nodes · "
                         f"{summary['total_carbon_kg']:.0f} kg CO2e · "
                         f"{summary['system_status']} · {len(sig)} active"),
                "severity": "critical" if summary["system_status"] == "CRITICAL" else "info",
            })
        except Exception as exc:
            broker.publish({"agent": "monitor", "phase": "observe",
                            "text": f"monitor error: {exc}", "severity": "info"})


def _refresh_fast(state=None) -> dict:
    """Detection-only refresh (no LLM) for the mutating endpoints, so buttons
    respond instantly instead of blocking on narrative generation. The LLM
    narrative is kept from the last /api/scan and regenerated on demand."""
    global _LAST
    state = state or state_store.load_state()
    results = orchestrator.quick_results(state)
    summary = orchestrator.summarize(state, results)
    _LAST = {"results": results, "summary": summary, "ts": time.time(), "state": state}
    return _LAST


def _ensure() -> dict:
    return _LAST if _LAST is not None else _refresh()


def _findings_payload(last: dict) -> dict:
    results = last["results"]
    corr = results["orchestrator"]
    return {
        "cyber": results["cyber"]["findings"],
        "carbon": results["carbon"]["findings"],
        "incidents": corr["incidents"],
        "report": corr["report"],
        "cyber_narrative": _NARRATIVE["cyber"],
        "carbon_narrative": _NARRATIVE["carbon"],
        "provider": _NARRATIVE["provider"],
    }


@app.on_event("startup")
async def _startup():
    state_store.ensure_baseline()
    _refresh()
    asyncio.create_task(_monitor_loop())


# ===========================================================================
# Endpoints
# ===========================================================================

@app.get("/api/state")
def get_state():
    """Current world — the monitor's live in-memory state (with the traffic
    wave) when available, else the file."""
    if _LAST and _LAST.get("state"):
        return _LAST["state"]
    return state_store.load_state()


@app.get("/api/findings")
def get_findings():
    """Latest cyber + carbon findings + correlated incidents."""
    return _findings_payload(_ensure())


@app.get("/api/regions")
def get_regions():
    """Per-region carbon intensity + the servers running there — for the
    workload-routing visualization. Sorted cleanest-grid first."""
    from carbon_data import get_carbon_intensity

    state = state_store.load_state()
    regions: dict[str, dict] = {}
    for s in state["servers"]:
        r = s["region"]
        if r not in regions:
            ci = get_carbon_intensity(r)
            regions[r] = {
                "region": r,
                "intensity": ci.gco2_per_kwh,
                "source": ci.source,
                "is_dirty": ci.is_dirty,
                "is_clean": ci.is_clean,
                "servers": [],
            }
        regions[r]["servers"].append({
            "id": s["id"],
            "cpu": s["cpu_utilization"],
            "status": s["status"],
            "residency_locked": s.get("data_residency", "none") not in (None, "none", ""),
        })
    ordered = sorted(regions.values(), key=lambda x: x["intensity"])
    greenest = ordered[0]["region"] if ordered else None
    return {"regions": ordered, "greenest": greenest}


@app.get("/api/forecast")
def get_forecast():
    """Next-24h carbon forecast per region + the greenest upcoming window —
    powers temporal (carbon-aware) scheduling of deferrable workloads."""
    from carbon_data import get_carbon_forecast

    state = state_store.load_state()
    out = {}
    for region in sorted({s["region"] for s in state["servers"]}):
        f = get_carbon_forecast(region)
        out[region] = {
            "now": f.now,
            "points": [p["intensity"] for p in f.points],
            "best_offset_h": f.best_offset_h,
            "best_intensity": f.best_intensity,
            "reduction_pct": f.reduction_pct,
            "source": f.source,
        }
    return out


@app.get("/api/summary")
def get_summary():
    """Totals: security score, total carbon, total cost, # critical, status."""
    last = _ensure()
    return {
        **last["summary"],
        "last_updated": last.get("ts"),
        "monitor_interval_s": MONITOR_INTERVAL_SECONDS,
        "autopilot": _autopilot,
    }


@app.post("/api/autopilot")
def set_autopilot(on: bool):
    """Toggle autonomous mode: the agent applies safe scaling itself."""
    global _autopilot
    _autopilot = on
    broker.publish({"agent": "autopilot", "phase": "reason",
                    "text": f"Autopilot {'ENABLED — agent will self-scale to SLO' if on else 'disabled — human-in-the-loop'}.",
                    "severity": "info"})
    return {"autopilot": _autopilot}


@app.post("/api/scan")
async def post_scan():
    """Run both agents once. Streams agent thoughts via /api/stream."""
    loop = asyncio.get_running_loop()
    emit = _make_emit(loop)
    last = await loop.run_in_executor(None, lambda: _refresh(None, emit))
    broker.publish({"agent": "system", "phase": "done",
                    "text": "Scan complete.", "severity": "info"})
    return _findings_payload(last)


@app.post("/api/attack")
async def post_attack():
    """Trigger the local attack simulation, mutate state, return new state."""
    loop = asyncio.get_running_loop()
    emit = _make_emit(loop)
    result = await loop.run_in_executor(
        None, lambda: attack_simulator.simulate_attack(emit=emit)
    )
    last = await loop.run_in_executor(None, lambda: _refresh_fast(result["state"]))
    broker.publish({"agent": "system", "phase": "done",
                    "text": "Attack simulated.", "severity": "critical"})
    return {
        "state": result["state"],
        "carbon_spike_pct": result["carbon_spike_pct"],
        "summary": last["summary"],
        "findings": _findings_payload(last),
    }


@app.post("/api/remediate")
async def post_remediate(steps: str | None = None):
    """Trigger remediation, re-scan to verify, return result + savings.

    Optional ?steps=rotate_credentials (comma-separated) runs a partial heal to
    demonstrate the failure mode (the miner survives credential rotation).
    """
    step_list = [s.strip() for s in steps.split(",")] if steps else None
    loop = asyncio.get_running_loop()
    emit = _make_emit(loop)
    report = await loop.run_in_executor(
        None, lambda: remediation.remediate(emit=emit, steps=step_list)
    )
    last = await loop.run_in_executor(None, lambda: _refresh_fast(report["state"]))
    broker.publish({"agent": "system", "phase": "done",
                    "text": "Remediation complete.", "severity": "info"})
    # Drop the bulky state from the report; the dashboard polls /api/state.
    report_out = {k: v for k, v in report.items() if k != "state"}
    return {
        "report": report_out,
        "summary": last["summary"],
        "findings": _findings_payload(last),
    }


@app.post("/api/action")
async def post_action(server_id: str, type: str):
    """Execute a lifecycle action on a server (terminate | hibernate) so the
    choice has a real, visible effect: terminate removes the instance; hibernate
    stops its compute. State mutates, then findings/summary are recomputed."""
    loop = asyncio.get_running_loop()

    def do():
        with state_store.transaction():
            state = state_store.load_state()
            srv = state_store.get_server(state, server_id)
            if srv is None:
                return False
            if type == "terminate":
                state["servers"] = [s for s in state["servers"] if s["id"] != server_id]
            elif type == "hibernate":
                srv["status"] = "hibernated"
                srv["cpu_utilization"] = 0
                srv["gpu_utilization"] = 0
            elif type in ("scale_down", "scale_up"):
                # Apply the SLO-driven target replica count + projected latency.
                finding = tools.check_scaling(srv)
                if not finding:
                    return False
                m = finding["metrics"]
                srv["replicas"] = m["target_replicas"]
                srv["latency_p95_ms"] = m["projected_latency_ms"]
            else:
                return False
            state_store.save_state(state)
            return True

    ok = await loop.run_in_executor(None, do)
    if ok:
        broker.publish({"agent": "orchestrator", "phase": "act",
                        "text": f"{type.capitalize()} applied to {server_id}.",
                        "severity": "info"})
    last = await loop.run_in_executor(None, lambda: _refresh_fast())
    return {"ok": ok, "summary": last["summary"], "findings": _findings_payload(last)}


@app.post("/api/reset")
async def post_reset():
    """Convenience for re-running the demo: restore the pristine baseline."""
    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, state_store.reset_to_baseline)
    last = await loop.run_in_executor(None, lambda: _refresh_fast(state))
    return {"summary": last["summary"]}


@app.get("/api/stream")
async def stream():
    """SSE endpoint — streams agent ReAct thoughts live (Reason/Act/Observe)."""
    q = broker.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broker.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def root():
    return {"service": "ConstructSentry API", "endpoints": [
        "/api/state", "/api/findings", "/api/summary",
        "/api/scan", "/api/attack", "/api/remediate", "/api/stream", "/api/reset",
    ]}
