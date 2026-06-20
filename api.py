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
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import attack_simulator
import orchestrator
import remediation
import state_store

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
    _LAST = {"results": results, "summary": summary, "ts": time.time()}
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


def _incident_signature(results: dict) -> dict:
    return {
        i["server_id"]: (i["category"], i["severity"])
        for i in results["orchestrator"]["incidents"]
    }


async def _monitor_loop():
    global _LAST, _prev_sig
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
        try:
            state = await loop.run_in_executor(None, state_store.load_state)
            results = await loop.run_in_executor(None, orchestrator.quick_results, state)
            summary = orchestrator.summarize(state, results)
            _LAST = {"results": results, "summary": summary, "ts": time.time()}

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

            # Heartbeat so the feed visibly shows the monitor is always running.
            broker.publish({
                "agent": "monitor", "phase": "reason",
                "text": (f"sweep · {len(state['servers'])} nodes · "
                         f"{summary['total_carbon_kg']:.0f} kg CO2e · "
                         f"{summary['system_status']} · {len(sig)} active"),
                "severity": "critical" if summary["system_status"] == "CRITICAL" else "info",
            })
        except Exception as exc:
            broker.publish({"agent": "monitor", "phase": "observe",
                            "text": f"monitor error: {exc}", "severity": "info"})


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
    """Current cloud_state.json — all servers + status."""
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


@app.get("/api/summary")
def get_summary():
    """Totals: security score, total carbon, total cost, # critical, status."""
    last = _ensure()
    return {
        **last["summary"],
        "last_updated": last.get("ts"),
        "monitor_interval_s": MONITOR_INTERVAL_SECONDS,
    }


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
    last = await loop.run_in_executor(None, lambda: _refresh(result["state"], emit))
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
    last = await loop.run_in_executor(None, lambda: _refresh(report["state"], emit))
    broker.publish({"agent": "system", "phase": "done",
                    "text": "Remediation complete.", "severity": "info"})
    # Drop the bulky state from the report; the dashboard polls /api/state.
    report_out = {k: v for k, v in report.items() if k != "state"}
    return {
        "report": report_out,
        "summary": last["summary"],
        "findings": _findings_payload(last),
    }


@app.post("/api/reset")
async def post_reset():
    """Convenience for re-running the demo: restore the pristine baseline."""
    loop = asyncio.get_running_loop()
    state = await loop.run_in_executor(None, state_store.reset_to_baseline)
    last = await loop.run_in_executor(None, lambda: _refresh(state))
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
