# ConstructSentry

**Dual-agent cloud monitoring for the construction-tech industry — one engine
that catches cyber-security risk *and* carbon/energy waste at the same time,
because in the cloud they're usually the same root cause.**

> When an attacker brute-forces a construction cloud server and turns it into a
> crypto-mining node, they create BOTH a security breach AND a 24/7 "zombie
> energy" drain. Killing the attack protects blueprint data, shuts down wasted
> computation, lowers the cloud bill, and stops unnecessary CO₂.
> **One action, three wins: security + cost + carbon.**

A **cyber agent** and a **carbon agent** each scan a (simulated) construction
cloud; an **orchestrator** correlates their findings into unified, prioritized,
plain-language recommendations with concrete numbers (`$` saved, `kg CO₂e`
prevented). Everything runs on a visible **Reason → Act → Observe (ReAct)** loop
and is demoed through a live three-phase scenario:
**healthy baseline → attack + carbon surge → one-click remediation.**

---

## What's real vs. simulated

- ✅ **Real** detection logic (security rules + a physical power/carbon model).
- ✅ **Real** carbon data — the [Electricity Maps](https://www.electricitymaps.com/)
  API, with a labeled fallback table when no key is present.
- ✅ **Real** agent reasoning (Claude / Gemini) — with a deterministic fallback
  so the demo always runs offline.
- 🧪 **Simulated** environment (`cloud_state.json`) and **simulated, local-only**
  attack. No real network or server is ever touched.

---

## Architecture

```
React + Tailwind dashboard (browser)
        │  HTTP for actions, SSE for live agent thoughts
        ▼
FastAPI layer (api.py)  ── thin translator, no business logic
        │  direct Python calls
        ▼
agents: cyber_agent · carbon_agent · orchestrator · react_loop
        │
        ▼
cloud_state.json  (the simulated construction cloud)
```

### Backend modules

| File | Role |
|---|---|
| `cloud_state.json` | The simulated cloud (10 servers + project Gantt) |
| `carbon_data.py` | Electricity Maps client + fallback intensity table |
| `tools.py` | All detection rules + the power/carbon model (pure functions) |
| `llm.py` | One `call_llm()` abstraction (Anthropic / Gemini / offline) |
| `cyber_agent.py` | Security agent |
| `carbon_agent.py` | Carbon/energy agent (good-carbon vs bad-carbon judgment) |
| `orchestrator.py` | Correlation engine — fuses findings into compound incidents |
| `react_loop.py` | The Reason → Act → Observe engine |
| `state_store.py` | Load/save state + pristine baseline snapshot |
| `attack_simulator.py` | Phase 2 — local attack signature injection |
| `remediation.py` | Phase 3 — one-click heal |
| `main.py` | The `rich` CLI demo |
| `api.py` | FastAPI layer (incl. SSE stream) |
| `dashboard/` | React + Vite + Tailwind dashboard |

---

## Quick start

### 1. Backend

```bash
# from the repo root
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
```

**Run the CLI demo** (no frontend needed):

```bash
python main.py            # interactive: Enter advances each phase
python main.py --auto     # auto-advancing
```

**Or run the API** (for the dashboard):

```bash
uvicorn api:app --reload --port 8000
```

### 2. Frontend

```bash
cd dashboard
npm install
npm run dev          # http://localhost:5173
```

Open **http://localhost:5173** (use `localhost`, not `127.0.0.1`). The Vite dev
server proxies `/api` to the backend on `:8000`.

### 3. The 3-click demo

1. **Run Scan** — agents scan the calm fleet → **HEALTHY**.
2. **⚠ Simulate Attack** — a local attack signature hits the target → UI slams
   to **CRITICAL**: red takeover, carbon spikes, the compromised host flashes,
   agents detect & correlate live, the compound incident appears.
3. **Heal** — one-click remediation → **HEALED**: carbon drops, status returns
   to green, and a final savings report slides in.

---

## Configuration (optional)

Set environment variables to enable live data/reasoning (all optional):

```bash
export ELECTRICITY_MAPS_API_KEY=...   # live grid carbon intensity
export ANTHROPIC_API_KEY=...          # Claude reasoning (else Gemini, else offline)
export GEMINI_API_KEY=...             # Gemini reasoning
```

With no keys set, the app uses the fallback carbon table and deterministic
agent reasoning — clearly labeled as such in the UI.

---

## Deployment notes

The **dashboard** is a static Vite build and deploys cleanly to Vercel
(`dashboard/` as the project root, build `npm run build`, output `dist`).

The **backend** keeps mutable state (`cloud_state.json`), an in-memory SSE
broker, and long-lived SSE connections, so it needs a **persistent process** —
host it on Render / Railway / Fly.io (or run locally for the demo) rather than
serverless. Point the dashboard at it by setting the Vite proxy target (or an
API base URL) to the deployed backend.

---

## Built with AI tools

This project was built with **[Claude Code](https://claude.com/claude-code)**
(Anthropic's Claude Opus) used for architecture, implementation, and testing of
both the backend agents and the dashboard. Agent reasoning at runtime is powered
by the Claude API (with a Google Gemini option and an offline deterministic
fallback).
