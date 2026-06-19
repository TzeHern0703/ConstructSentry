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


def _refresh(state=None, emit=None) -> dict:
    global _LAST
    state = state or state_store.load_state()
    results = orchestrator.run(state, emit=emit)
    summary = orchestrator.summarize(state, results)
    _LAST = {"results": results, "summary": summary}
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
        "cyber_narrative": results["cyber"]["narrative"],
        "carbon_narrative": results["carbon"]["narrative"],
    }


@app.on_event("startup")
def _startup():
    state_store.ensure_baseline()
    _refresh()


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


@app.get("/api/summary")
def get_summary():
    """Totals: security score, total carbon, total cost, # critical, status."""
    return _ensure()["summary"]


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
async def post_remediate():
    """Trigger remediation, restore safe state, return result + savings."""
    loop = asyncio.get_running_loop()
    emit = _make_emit(loop)
    report = await loop.run_in_executor(
        None, lambda: remediation.remediate(emit=emit)
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
