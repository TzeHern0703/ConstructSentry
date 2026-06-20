# ConstructSentry

> **ImagineHack 2026 · Track 2 (HILTI) — Secure & Energy-Aware Cloud Platforms for Construction Tech**
> **Team:** derited (Group 32)
> **Leader:** Pee Tze Hern
> **Members:** Kam Joshua Jing Hong · Tee Jia King · Yeoh Xin Hui · Koh Hui Yuan

---

**Dual-agent cloud monitoring for the construction-tech industry — one engine
that catches cyber-security risk *and* carbon/energy waste at the same time,
because in the cloud they're usually the same root cause.**

> When an attacker brute-forces a construction cloud server and turns it into a
> crypto-mining node, they create BOTH a security breach AND a 24/7 "zombie
> energy" drain. Killing the attack protects blueprint data, shuts down wasted
> computation, lowers the cloud bill, and stops unnecessary CO₂.
> **One action, three wins: security + cost + carbon.**

A **cyber agent** and a **carbon agent** continuously scan a (simulated)
construction cloud; an **orchestrator** correlates their findings into unified,
prioritized, plain-language recommendations with concrete numbers (`$` saved,
`kg CO₂e` prevented). Everything runs on a visible **Reason → Act → Observe
(ReAct)** loop and is demoed through a live three-phase scenario:
**healthy baseline → attack + carbon surge → one-click remediation.**

A background monitor re-scans the fleet every few seconds (not just on click),
so detection is genuinely *continuous*, and every remediation is **verified by
re-scanning** rather than assumed.

---

## What's real vs. simulated

- ✅ **Real** detection logic (security rules + a non-linear power/carbon model
  with regional PUE).
- ✅ **Real** carbon data — the [Electricity Maps](https://www.electricitymaps.com/)
  API (live grid intensity *and* last-24h history for green scheduling), with a
  labeled fallback table when no key is present.
- ✅ **Real** agent reasoning (Claude / Gemini), surfaced in the dashboard's
  **AI Analysis** panel — with a deterministic fallback so the demo always runs
  offline.
- ✅ **Real** continuous monitoring (background re-scan) and **verified**
  remediation (re-scan to confirm the fix worked).
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
| `api.py` | FastAPI layer (SSE stream + 6s continuous-monitor loop) |
| `dashboard/` | React + Vite + Tailwind dashboard |

### Data model (`cloud_state.json`)

Each server carries the fields both domains need, plus the construction-specific
business context:

- *Sizing / carbon:* `instance_type`, `cpu_utilization`, `gpu_utilization`,
  `runtime_hours_this_month`, `region`, `monthly_cost_usd`
- *Security config:* `open_ports`, `ssh_exposed`, `encrypted_at_rest`,
  `iam_scope`, `mfa_enabled`, `failed_login_attempts_last_hour`,
  `last_credential_rotation_days`
- *Business / governance:* `owner_subcontractor`,
  `subcontractor_contract_active`, `scheduled_tasks`, **`data_residency`**
  (sovereignty lock), **`dataset_size_gb`** (data-transit carbon),
  **`asset_criticality`** (security-score weighting)

---

## Engineering depth & design decisions

Things that are easy to get wrong in a PoC and how this project handles them:

- **Continuous monitoring, not snapshots.** A background loop (`api.py
  _monitor_loop`) re-scans every 6 s, diffs against the previous sweep, and
  pushes only *changes* (new / escalated / cleared) plus a heartbeat over SSE —
  it catches a change even if no one clicks anything.
- **Deterministic detection, LLM judgment.** Detection rules (`tools.py`) are
  pure and reproducible *on purpose* — you don't want an LLM guessing whether
  port 22 is open. The LLM (Claude/Gemini) does the judgment layer: ranking,
  good-carbon-vs-bad-carbon, and the plain-language analysis shown in the UI.
- **Realistic carbon physics.** Power uses the non-linear Fan et al. (Google)
  server model, not a straight line, and applies a **load-dependent regional
  PUE** (datacenter cooling) — so the same workload emits more in hot Singapore
  (PUE ≈ 1.5) than in cold Sweden (≈ 1.1). Grid intensity is live from
  Electricity Maps.
- **Sovereignty- & transit-aware green scheduling.** Relocation isn't blindly
  recommended: the engine accounts for the **carbon cost of moving the dataset**
  and refuses cross-border moves for **residency-locked** blueprint data —
  time-shifting in-region instead. The time-shift saving is computed from each
  grid's **real last-24h swing** (Electricity Maps history), not a constant.
- **Carbon-aware autoscaling (carbon = ops, not a side report).** Servers carry
  p95 latency, a latency SLO and replica count; carbon/cost scale with replicas.
  The agent keeps the *fewest* replicas that still meet the SLO — too many is
  carbon+cost waste (scale down), a latency breach needs capacity (scale up). So
  carbon is minimized *subject to* the performance SLO — the integration most
  PoCs miss.
- **Graduated autonomy (safe = auto, risky = approval).** A live traffic wave
  makes latency fluctuate; with **Autopilot ON** the agent autonomously does the
  *safe, reversible* work — scaling each workload to its SLO. But a *high-stakes*
  action (healing a compromised prod host = killing processes) is **gated behind
  human approval even in Autopilot**: the agent lists the problems it found and
  the remediation it proposes and waits for the operator to **Approve / Deny** —
  like a real SOC runbook, not a silent auto-fix.
- **Predictive autoscaling (not just reactive).** A short-horizon load forecast
  lets the agent **pre-scale before** latency breaches the SLO, rather than only
  reacting after.
- **Identifies carbon-intensive / inefficient workloads with the "why".** The
  Efficiency view ranks workloads by emissions and explains each (oversized
  instance / dirty grid / replicas / near-idle / cooling), with utilization and
  the carbon wasted on idle capacity — answering the challenge directly.
- **Business framing.** The AI Report includes a business view: annualized $ and
  CO₂e (in relatable terms), and why it matters in construction terms (blueprint
  IP, subcontractor governance, project margin, ESG reporting).
- **Per-workload lifecycle actions (not one-size-fits-all "shut down").** The
  orchestrator recommends the *right* action per server — **terminate** (gone
  for good), **hibernate** (stop compute, keep disk, wake on demand),
  **right-size**, **route**, or **time-shift** — each with its own savings math.
  Idle/unneeded servers expose a **terminate ↔ hibernate toggle** (the choice
  changes the numbers), and **Apply** actually executes it: terminate removes
  the instance, hibernate stops it — so the fleet, Carbon Map, wasted spend and
  total carbon all visibly update.
- **Workload-routing visualization (Carbon Map).** Region lanes ordered
  cleanest-grid-first, coloured by *live* carbon intensity, with each server as
  a chip in its region (residency-locked workloads marked 🔒) — makes the
  "route to a greener grid vs time-shift in place" decision tangible.
- **Actionable cost metric.** The headline money number is *recoverable/wasted
  spend* (what you can reclaim by acting on the incidents), not static total
  spend — so it's meaningful and moves through the demo.
- **Verified remediation.** Heal is modelled as discrete IR steps (isolate →
  kill process → rotate credentials) where killing the process is what lowers
  CPU; the host then settles into its legitimate operating range (not a frozen
  snapshot replay). It then **re-scans to verify** — a partial heal (rotate
  creds only) correctly *fails* verification because the miner is still running.
- **Asset-weighted security score.** Findings are weighted by
  `asset_criticality`, and a compromised *critical* asset hard-caps the score —
  so a large fleet can't dilute one core breach into a falsely passing grade,
  and minor issues on disposable nodes don't crater it to zero.
- **Concurrency-safe state.** `state_store.py` serializes read-modify-write with
  a reentrant lock and writes atomically (temp file + `os.replace`), so the
  monitor loop and user actions can't corrupt `cloud_state.json`.

*Known roadmap (not bottlenecks at demo scale):* the monitor scans the fleet
serially — fine for 10 nodes (carbon lookups are cached per region); scaling to
thousands of nodes would move to a concurrent pipeline + incremental/sampled
streaming.

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
3. **Heal** — one-click remediation (isolate → kill process → rotate creds) is
   re-scanned to **verify** → **HEALED**: carbon drops, status returns to green,
   and a verified savings report slides in.

Or flip **Autopilot ON** and just watch: the agent autonomously scales workloads
to their SLO, and on an attack it **requests approval** to heal (a banner with
Approve / Deny) — safe actions auto, risky actions gated.

Throughout, the **Agent Reasoning** feed streams live Reason→Act→Observe steps
(including the monitor's heartbeat and 🤖 Autopilot actions). The left panel
toggles **Fleet / Efficiency / Carbon Map / Scaling**: Efficiency flags
carbon-intensive/inefficient workloads with the why; Carbon Map shows live grid
+ 24h forecast; Scaling is the latency-vs-SLO benchmark with Apply. On an
incident, switch **Terminate ↔ Hibernate** and hit **Apply**; **AI Report**
exports the full analysis (with business impact) as Markdown.

---

## Configuration (optional)

Copy `.env.example` to `.env` and fill in any keys (all optional — the app
auto-loads `.env` on startup):

```bash
cp .env.example .env
# then edit .env:
ELECTRICITY_MAPS_API_KEY=...   # live grid carbon intensity
ANTHROPIC_API_KEY=...          # Claude reasoning (else Gemini, else offline)
GEMINI_API_KEY=...             # Gemini reasoning
```

With no keys set, the app uses the fallback carbon table and deterministic
agent reasoning — clearly labeled as such in the UI. `.env` is gitignored, so
your keys never get committed.

---

## Deployment notes

The **dashboard** is a static Vite build and deploys cleanly to Vercel
(`dashboard/` as the project root, build `npm run build`, output `dist`).

The **backend** keeps mutable state (`cloud_state.json`), an in-memory SSE
broker, a background monitor loop, and long-lived SSE connections, so it needs a
**persistent process** — not serverless (so plain Vercel won't host it). The
easiest path is the included **Docker + `render.yaml`**: one service builds the
dashboard and runs FastAPI, which serves both the UI and the API at one URL
(see the *Deploy to Render* button above). The same Docker image runs on
Railway / Fly.io / any container host. For local dev, use the two-process setup
below (Vite proxies `/api` to uvicorn).

---

## Built with AI tools

This project was built with **[Claude Code](https://claude.com/claude-code)**
(Anthropic's Claude Opus) used for architecture, implementation, and testing of
both the backend agents and the dashboard. Agent reasoning at runtime is powered
by the Claude API (with a Google Gemini option and an offline deterministic
fallback).
