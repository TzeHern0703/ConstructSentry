# ConstructSentry — Research & Tinkering Guide

A hands-on reference for experimenting with the system: **what you can change,
where, and where to see the effect.** Everything is data-driven — nothing in the
detection results is hardcoded, so editing the environment changes the output.

---

## 1. Where the data lives

The whole simulated cloud is one file:

```
constructsentry/cloud_state.json
```

It has `servers` (a list of 10 server objects) and `project_gantt`
(subcontractor contracts). Each server object is what you edit.

### Two ways to edit

| Mode | How | Survives Reset? |
|---|---|---|
| **Temporary** (experiment) | Edit `cloud_state.json`, save | ❌ No — Reset/Attack/Heal overwrite it |
| **Permanent** (change the seed) | Edit **both** `cloud_state.json` **and** `cloud_state.baseline.json` (same change) | ✅ Yes |

> `cloud_state.baseline.json` is the pristine snapshot the **Reset** and **Heal**
> buttons restore from. It's auto-generated if deleted (`python state_store.py`).

### You don't need to restart

The backend's **continuous monitor re-reads the file every 6 seconds**. So:
edit → save → wait ~6 s → the dashboard updates on its own (no button click).

---

## 2. How to edit a value (JSON basics)

Find the server by its `id`, change the value after the colon, save. Three
value types:

| Type | Example field | How to change |
|---|---|---|
| **Number** | `"cpu_utilization": 47,` | Just change the number → `95`. Keep the comma. |
| **Boolean** | `"ssh_exposed": false,` | `true` / `false` — lowercase, **no quotes**. |
| **Text** | `"iam_scope": "scoped",` | Keep the `"..."` quotes → `"wildcard"`. |
| **Array** | `"open_ports": [443],` | Comma-separated → `[443, 22]`. Empty = `[]`. |

JSON rules: numbers raw, booleans lowercase unquoted, text quoted, every value
except the last in an object needs a trailing comma.

A full server object looks like this:

```json
{
  "id": "fieldwire-api-prod",
  "role": "Fieldwire field-ops API",
  "region": "us-east-1",
  "instance_type": "c6i.2xlarge",
  "cpu_utilization": 47,
  "gpu_utilization": 0,
  "runtime_hours_this_month": 720,
  "monthly_cost_usd": 510,
  "open_ports": [443],
  "ssh_exposed": false,
  "encrypted_at_rest": true,
  "iam_scope": "scoped",
  "mfa_enabled": true,
  "failed_login_attempts_last_hour": 4,
  "last_credential_rotation_days": 21,
  "owner_subcontractor": "HILTI Internal",
  "subcontractor_contract_active": true,
  "scheduled_tasks": [{"task": "field sync batch", "active": true}],
  "status": "healthy",
  "data_residency": "none",
  "dataset_size_gb": 120,
  "asset_criticality": "high"
}
```

---

## 3. Field reference — change X, see Y

### Security fields (handled in `tools.py`)

| Field | Set it to… | Triggers (rule) | Severity | Where you see it |
|---|---|---|---|---|
| `failed_login_attempts_last_hour` | `> 100` (e.g. 450) | `BRUTE_FORCE` | 🔴 critical | Status→CRITICAL, security score drops, Agent feed, Incident |
| `ssh_exposed` + port 22 in `open_ports` | `true` + `[443, 22]` | `EXPOSED_SSH` | 🟡 warning | Incident, AI Analysis |
| `encrypted_at_rest` | `false` | `NO_ENCRYPTION` | 🟡 warning | Incident |
| `iam_scope` | `"wildcard"` | `WILDCARD_IAM` | 🟡 warning | Incident |
| `mfa_enabled` | `false` | `NO_MFA` | 🟡 warning | Incident |
| `last_credential_rotation_days` | `> 90` (e.g. 200) | `STALE_CREDENTIALS` | 🟡 warning | Incident |
| `subcontractor_contract_active` | `false` | `ORPHANED_ACCESS` | 🔴 critical | Incident (score drops; status stays HEALTHY*) |

\* `ORPHANED_ACCESS` is a serious *latent* risk so it's critical severity, but
the **system status** flips to CRITICAL only on an *active compromise*
(`BRUTE_FORCE` / `BAD_CARBON_COMPROMISE`).

### Carbon / cost / sizing fields (handled in `tools.py` + `carbon_data.py`)

| Field | Effect | Triggers (rule) | Where you see it |
|---|---|---|---|
| `cpu_utilization` | More load → more power → more carbon | `> 80` + no active task → `BAD_CARBON_COMPROMISE` (🔴) | Carbon number/chart, status, Incident |
| `gpu_utilization` | Same, **only on g5 instances** (others have no GPU) | feeds power model | Carbon number/chart |
| `instance_type` | Bigger type → higher max watts → more carbon | `OVER_PROVISIONED` if large + low util | Carbon, Incident |
| `region` | Changes grid carbon intensity **and** cooling PUE | `HIGH_CARBON_REGION` if dirty + deferrable | Carbon number/chart, Incident |
| `runtime_hours_this_month` | More hours → more energy | feeds `ZOMBIE` | Carbon number |
| `cpu`+`gpu` ~0 with high runtime | idle waste | `ZOMBIE` (🟡) | Incident |
| `monthly_cost_usd` | Fleet cost total + savings figures | — | SummaryRow "Monthly Cost", Incident savings |
| `data_residency` | `"none"` = relocatable; a region code (e.g. `"APAC"`, `"EU"`) = locked | switches relocate ↔ time-shift | Incident recommendation text |
| `dataset_size_gb` | Bigger = more data-transit carbon | can flip relocate→time-shift | Incident recommendation |
| `asset_criticality` | `critical`/`high`/`medium`/`low` — weights the score | a compromised `critical` asset caps score at 30 | SummaryRow security score |
| `status` | `healthy`/`warning`/`critical` | card dot colour | ServerGrid |

### Detection thresholds (exact, from `tools.py`)

- `BRUTE_FORCE`: `failed_login_attempts_last_hour > 100`
- `STALE_CREDENTIALS`: `last_credential_rotation_days > 90`
- `OVER_PROVISIONED`: instance max watts ≥ 600 **and** CPU < 10 **and** GPU < 10
- `ZOMBIE`: CPU ≤ 2 **and** GPU ≤ 2 **and** runtime > 600 h
- `HIGH_CARBON_REGION`: grid intensity ≥ 400 gCO₂/kWh **and** workload is deferrable
- `GOOD/BAD carbon`: CPU > 80 → GOOD if a scheduled task is active, BAD (compromise) if not

---

## 4. The carbon formula (so you can predict the number)

```
IT power  = max_watts(instance_type) × ( 0.35 + 0.65 × f(utilization) )
            f(u) = 2u − u^1.4              (Fan et al. non-linear curve)
facility  = IT power × PUE(region, utilization)   (cooling overhead)
energy    = facility × runtime_hours / 1000        → kWh
carbon    = energy × grid_intensity(region) / 1000 → kg CO₂e
```

- `max_watts` table & `PUE` table: `tools.py` / `carbon_data.py`
- `grid_intensity`: live from Electricity Maps (or fallback table), per region
- GPU instances (`g5*`) weight GPU 0.6 / CPU 0.4 in `utilization`; others use CPU

Example regions (live values vary hourly): Sweden ≈ 22, Canada ≈ 47,
Ireland ≈ 330, US-East ≈ 365, Singapore ≈ 495, Indonesia ≈ 675 gCO₂/kWh.
PUE: cold grids ≈ 1.1, hot/humid ≈ 1.5.

---

## 4b. Recommended actions, Carbon Map & Apply

Each incident gets a **per-workload action** (shown as a coloured chip), chosen
from signals:

| Signal | Recommended action | Savings model |
|---|---|---|
| Owner contract inactive (orphaned) | **Terminate** (default) | 100% cost + carbon |
| Idle but still contracted + has a task | **Hibernate** (default) | ~85% cost, ~95% carbon (disk kept) |
| Large instance, in use | **Right-size** | ~70% |
| Deferrable, dirty grid, relocatable | **Route** | grid delta − transit |
| Deferrable, residency-locked | **Time-shift** | real intraday swing |
| Active compromise | **Isolate & restore** | reclaim instance + attack delta |
| Pure misconfig | **Harden** | security only |

Where it matters (idle/unneeded servers) the card shows a **Terminate ↔
Hibernate** toggle — switching shows that option's numbers + tradeoff. **Apply**
*executes* it: terminate removes the instance from the fleet; hibernate stops
its compute (`status: hibernated`, ~3% disk-only power, excluded from
detection). The fleet, **Carbon Map**, wasted spend and total carbon all update.

The **Carbon Map** (left-panel "Carbon Map" tab) shows region lanes ordered
cleanest-grid-first, coloured by live intensity, each server a chip (🔒 =
residency-locked, can't move). It polls `/api/regions` every 3 s, so live grid
changes and any region edits show up automatically.

---

## 4c. Carbon-aware autoscaling, Autopilot & heal approval

Scalable workloads carry extra fields (edit them to experiment):

| Field | Meaning | Effect |
|---|---|---|
| `replicas` | running replica count | carbon & cost scale with it |
| `latency_p95_ms` | current p95 latency | drives scale up/down |
| `latency_slo_ms` | latency target | the benchmark to hold |

The agent keeps the **fewest replicas that meet the SLO**:
- low latency + headroom → **Scale down** (carbon waste) ·
  high latency > SLO → **Scale up** (capacity to hold the SLO).
- `target = ceil(latency × replicas / slo)`; latency scales inversely with
  replicas. See it in the **Scaling** tab (latency-vs-SLO bars).

**Graduated autonomy:**
- **Autopilot** (control-bar toggle) — the agent autonomously does the *safe*
  work each sweep: scaling each workload to its SLO (predictive — it pre-scales
  on a short load forecast). A live traffic wave keeps latency moving.
- **High-stakes = approval required** — healing a compromised host is gated:
  even in Autopilot the agent raises an **approval request** (banner with
  Approve / Deny); with Autopilot off, clicking **Heal** opens the same plan
  (problems found + proposed steps) to approve. Safe = auto, risky = your call.
- Terminate / Hibernate have one-click **Apply** on the incident card; Scale
  ↑/↓ has **Apply** in the Scaling tab.

The **Efficiency tab** ranks workloads by emissions and flags each as
carbon-intensive / inefficient / efficient with the *why* (oversized instance,
dirty grid, replicas, near-idle, cooling) + utilization + carbon wasted on idle.

```bash
curl -s -X POST "http://localhost:5173/api/autopilot?on=true"      # enable autonomy
curl -s    "http://localhost:5173/api/carbon"                       # per-workload efficiency
curl -s -X POST "http://localhost:5173/api/approve?server_id=bim-render-prod-02"  # approve a gated heal
curl -s -X POST "http://localhost:5173/api/action?server_id=fieldwire-api-prod&type=scale_down"
```

---

## 5. How to check a change took effect

1. **Dashboard** — wait ~6 s; numbers, server cards, incidents update on their
   own. The Agent feed prints `New incident: <server> — <category>`.
2. **Command line:**
   ```bash
   curl -s http://localhost:5173/api/summary    # score / carbon / recoverable / status
   curl -s http://localhost:5173/api/findings   # findings + incidents + actions
   curl -s http://localhost:5173/api/regions    # per-region intensity (Carbon Map)
   # execute a lifecycle action:
   curl -s -X POST "http://localhost:5173/api/action?server_id=blueline-staging-07&type=terminate"
   ```
3. **Restore:** click **Reset** (or `curl -X POST http://localhost:5173/api/reset`).

---

## 6. Ready-made experiments

Edit `cloud_state.json`, save, wait ~6 s, observe. (Server names are the `id`.)

1. **Turn a clean server into a compromised host**
   On `fieldwire-api-prod`: `cpu_utilization` → 95, `failed_login_attempts_last_hour`
   → 450, `ssh_exposed` → true, `open_ports` → `[443, 22]`, `scheduled_tasks` → `[]`.
   → becomes a 🔗 compound COMPROMISED HOST; status CRITICAL; score ~31.

2. **See a clean grid vs a dirty grid**
   On `bim-render-prod-01`: `region` → `"eu-north-1"` (Sweden) vs `"ap-southeast-3"`
   (Indonesia). Watch its carbon swing from ~16 kg to ~676 kg.

3. **Make an over-provisioned waste server**
   On any server: `instance_type` → `"g5.12xlarge"`, `cpu_utilization` → 3,
   `gpu_utilization` → 2. → `OVER_PROVISIONED` with a right-size recommendation.

4. **Trigger the orphaned-access rule (construction angle)**
   On any server: `subcontractor_contract_active` → false. → `ORPHANED_ACCESS`.

5. **Sovereignty vs transit (relocation logic)**
   On `bim-archive-render-02`: flip `data_residency` between `"APAC"` (locked →
   time-shift, ~15 kg) and `"none"` (relocate, ~617 kg net).

6. **Asset weighting**
   Compromise the same server with `asset_criticality` set to `"critical"` vs
   `"low"`; compare the security score (capped ~26 vs ~49).

7. **Terminate vs Hibernate (action changes the result)**
   On the `blueline-staging-07` incident, toggle **Terminate** vs **Hibernate**
   (numbers differ), then **Apply**: terminate drops the fleet 10→9 and wasted
   spend $4,110→$2,870; reset and instead **Hibernate** `bim-archive-render-02`
   to watch total carbon fall ~1790→~1090 kg (it's the biggest emitter).

8. **Autopilot autonomy + approval gate**
   Toggle **Autopilot ON**: the agent auto-scales workloads to their SLO on its
   own (watch the `🤖 Autopilot …` feed). Now **Simulate Attack** — instead of
   silently healing, the agent raises an **approval request** banner; click
   **Approve** to run the verified heal (safe actions auto, risky gated).

9. **Latency / scaling (raise load by hand)**
   Bump `latency_p95_ms` on `fieldwire-api-prod` above its `latency_slo_ms`
   (200) → the **Scaling** tab flips it red with a "scale up" arrow and a
   SCALE_UP incident appears; lower it well under the SLO → "scale down".

---

## 7. Code map (where each thing lives)

| File | What it does |
|---|---|
| `cloud_state.json` | the editable environment (10 servers + Gantt) |
| `tools.py` | all detection rules + power/carbon model (pure functions) |
| `carbon_data.py` | Electricity Maps client (intensity, PUE, 24h history) + fallback |
| `cyber_agent.py` / `carbon_agent.py` | run the rules + LLM narrative |
| `orchestrator.py` | correlate findings → incidents; `summarize` = score/status |
| `react_loop.py` | the Reason→Act→Observe engine |
| `state_store.py` | load/save (locked + atomic) + baseline snapshot |
| `attack_simulator.py` | Phase-2 local attack signature |
| `remediation.py` | Phase-3 heal (steps + verify) |
| `api.py` | FastAPI + SSE + the 6 s continuous-monitor loop |
| `main.py` | the `rich` CLI demo |
| `dashboard/` | React + Vite + Tailwind UI |

> Tip: to trace any number, start at the field in `cloud_state.json`, find the
> rule in `tools.py` that reads it, then the recommendation in
> `orchestrator.py` `_recommend`.
