"""tools.py — detection tools for ConstructSentry.

Pure, side-effect-free functions that both agents call. No LLM here and no I/O
beyond the carbon-intensity lookup, so every rule is unit-testable on its own
(PROJECT_SPEC Section 6 + build-order step 3).

Two families of tools:
  * Cyber detection rules    -> security findings
  * Carbon estimation + waste rules -> energy/carbon findings

Every detection function returns either None (no problem) or a finding dict:

    {
      "server_id": str,
      "type": str,          # short machine-ish code, e.g. "EXPOSED_SSH"
      "severity": str,      # "info" | "warning" | "critical"
      "evidence": str,      # plain-language explanation with the numbers
      "raw_rule": str,      # the function/rule name that fired
      "domain": str,        # "cyber" | "carbon"
      "metrics": dict,      # structured numbers for the orchestrator
    }
"""

from __future__ import annotations

from carbon_data import get_carbon_intensity, get_pue, greenest_region

# --- Severity ordering (used by the orchestrator to rank) ------------------

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def make_finding(server, type_, severity, evidence, raw_rule, domain, **metrics):
    """Build a finding dict in the standard shape."""
    return {
        "server_id": server["id"],
        "type": type_,
        "severity": severity,
        "evidence": evidence,
        "raw_rule": raw_rule,
        "domain": domain,
        "metrics": metrics,
    }


# ===========================================================================
# CYBER detection rules
# ===========================================================================

def check_exposed_ssh(server):
    """Flag if SSH is exposed and port 22 is open."""
    if server.get("ssh_exposed") and 22 in server.get("open_ports", []):
        return make_finding(
            server, "EXPOSED_SSH", "warning",
            f"SSH port 22 is open and exposed on {server['id']} "
            f"(open ports: {server['open_ports']}).",
            "check_exposed_ssh", "cyber",
        )
    return None


def check_encryption(server):
    """Flag if data is not encrypted at rest."""
    if not server.get("encrypted_at_rest", True):
        return make_finding(
            server, "NO_ENCRYPTION", "warning",
            f"Data on {server['id']} is NOT encrypted at rest — "
            f"blueprint/asset data is readable if disks are accessed.",
            "check_encryption", "cyber",
        )
    return None


def check_iam(server):
    """Flag if IAM scope is a wildcard (over-permissive)."""
    if server.get("iam_scope") == "wildcard":
        return make_finding(
            server, "WILDCARD_IAM", "warning",
            f"{server['id']} uses a wildcard IAM scope — any compromise grants "
            f"broad access across the account.",
            "check_iam", "cyber",
        )
    return None


def check_mfa(server):
    """Flag if MFA is disabled."""
    if not server.get("mfa_enabled", True):
        return make_finding(
            server, "NO_MFA", "warning",
            f"MFA is disabled on {server['id']} — credentials alone grant access.",
            "check_mfa", "cyber",
        )
    return None


def check_credential_rotation(server):
    """Flag if credentials haven't been rotated in over 90 days."""
    days = server.get("last_credential_rotation_days", 0)
    if days > 90:
        return make_finding(
            server, "STALE_CREDENTIALS", "warning",
            f"Credentials on {server['id']} last rotated {days} days ago "
            f"(> 90 day policy).",
            "check_credential_rotation", "cyber", days=days,
        )
    return None


def check_brute_force(server):
    """Flag CRITICAL if failed logins in the last hour exceed 100."""
    attempts = server.get("failed_login_attempts_last_hour", 0)
    if attempts > 100:
        return make_finding(
            server, "BRUTE_FORCE", "critical",
            f"{attempts} failed logins on {server['id']} in the last hour — "
            f"active brute-force / credential-stuffing attack.",
            "check_brute_force", "cyber", failed_logins=attempts,
        )
    return None


def check_orphaned_access(server, gantt):
    """Flag if the owning subcontractor's contract is inactive but the server
    is still running (the construction-specific differentiator)."""
    owner = server.get("owner_subcontractor")
    contract_active = server.get("subcontractor_contract_active", True)
    gantt_entry = (gantt or {}).get(owner, {})
    gantt_active = gantt_entry.get("active", True)

    if not contract_active or not gantt_active:
        contract_end = gantt_entry.get("contract_end", "unknown")
        return make_finding(
            server, "ORPHANED_ACCESS", "critical",
            f"{server['id']} is owned by '{owner}' whose contract ended "
            f"{contract_end} (inactive), but the server is still running with "
            f"live access — orphaned access path.",
            "check_orphaned_access", "cyber",
            owner=owner, contract_end=contract_end,
        )
    return None


CYBER_RULES = [
    check_exposed_ssh,
    check_encryption,
    check_iam,
    check_mfa,
    check_credential_rotation,
    check_brute_force,
]


def run_cyber_checks(server, gantt=None):
    """Run every cyber rule against one server. Returns a list of findings."""
    findings = [rule(server) for rule in CYBER_RULES]
    findings.append(check_orphaned_access(server, gantt))
    return [f for f in findings if f is not None]


# ===========================================================================
# CARBON estimation + waste rules
# ===========================================================================

# Approximate peak power draw (watts) per instance type. GPU instances (g5)
# include the GPU board(s); the rest are CPU/RAM bound.
INSTANCE_MAX_WATTS = {
    "m6i.large": 75,
    "m6i.xlarge": 150,
    "m6i.2xlarge": 300,
    "m6i.4xlarge": 600,
    "c6i.2xlarge": 280,
    "c6i.4xlarge": 560,
    "r6i.xlarge": 160,
    "g5.4xlarge": 1000,   # 1x A10G GPU + 16 vCPU
    "g5.12xlarge": 2500,  # 4x A10G GPU + 48 vCPU
}

DEFAULT_MAX_WATTS = 250

# A server still draws this fraction of peak power even when idle.
IDLE_POWER_FLOOR = 0.35

# Server power does NOT scale linearly with utilization. We use the Fan et al.
# (Google, 2007) empirical model f(u) = 2u - u^r, which matches measured machine
# power far better than a straight line (power rises fast at low load, then
# compresses near peak). r ~ 1.4.
POWER_CURVE_EXPONENT = 1.4

# Instances at or above this peak draw are considered "large" for the
# over-provisioning check.
LARGE_INSTANCE_WATTS = 600

# Role keywords that indicate a deferrable / batch workload (can be moved to a
# greener region or scheduled when the grid is clean).
DEFERRABLE_KEYWORDS = ("render", "archive", "calc", "sync", "batch", "reconcil")

# Energy intensity of long-haul data transfer (kWh per GB moved between
# regions). Relocating a workload is not free: moving its dataset across
# submarine cables / routers burns energy too. ~0.06 kWh/GB is a commonly cited
# figure for wide-area transfer.
NETWORK_KWH_PER_GB = 0.06

# A deferrable job time-shifted to the grid's greenest hours (in-region, no data
# movement) can avoid roughly this fraction of its carbon — a conservative take
# on intraday grid-intensity swings.
TIME_SHIFT_SAVING_FRACTION = 0.20


def is_relocatable(server):
    """True only if the data has no residency lock (can legally move regions)."""
    return server.get("data_residency", "none") in (None, "none", "")


def transit_carbon_kg(dataset_gb, source_intensity):
    """One-time carbon cost of moving a dataset out of its region."""
    return dataset_gb * NETWORK_KWH_PER_GB * source_intensity / 1000.0


def _greening_plan(server, carbon, intensity):
    """Decide how to cut a deferrable workload's carbon WITHOUT killing it.

    Accounts for (a) data-transit carbon — relocation must net-save after the
    one-time transfer cost — and (b) data sovereignty — blueprint/regulated data
    cannot be moved cross-border, so we time-shift in-region instead.

    Returns (action_text, metrics_dict).
    """
    g_region, g_value = greenest_region()
    greener_kg = round(carbon["power_kwh"] * g_value / 1000.0, 1)
    gross_savings = round(carbon["carbon_kg"] - greener_kg, 1)
    dataset_gb = server.get("dataset_size_gb", 0)
    transit_kg = round(transit_carbon_kg(dataset_gb, intensity.gco2_per_kwh), 1)
    shift_kg = round(carbon["carbon_kg"] * TIME_SHIFT_SAVING_FRACTION, 1)

    # 1) Data sovereignty: residency-locked data must not move cross-border.
    if not is_relocatable(server):
        residency = server.get("data_residency")
        action = (
            f"Data is residency-locked to {residency} — relocating to "
            f"{g_region} would save ~{gross_savings} kg/mo but is barred by data "
            f"sovereignty (and would cost ~{transit_kg} kg one-time transit for "
            f"{dataset_gb} GB). Instead, time-shift this deferrable job to the "
            f"grid's greenest hours in-region: ~{shift_kg} kg/mo, no data moved."
        )
        return action, {
            "plan": "time_shift",
            "residency_locked": True,
            "residency": residency,
            "relocate_to": g_region,
            "gross_relocate_kg": gross_savings,
            "transit_kg": transit_kg,
            "savings_kg": shift_kg,
        }

    # 2) Relocatable, but only if it net-saves after transit carbon.
    net = round(gross_savings - transit_kg, 1)
    if net <= 0:
        action = (
            f"Keep in-region: relocating to {g_region} would save only "
            f"~{gross_savings} kg/mo but moving {dataset_gb} GB costs ~{transit_kg} "
            f"kg transit (net {net} kg). Time-shift to greener hours instead: "
            f"~{shift_kg} kg/mo."
        )
        return action, {
            "plan": "time_shift",
            "residency_locked": False,
            "relocate_to": g_region,
            "gross_relocate_kg": gross_savings,
            "transit_kg": transit_kg,
            "savings_kg": shift_kg,
        }

    action = (
        f"Relocate this deferrable workload to {g_region} ({g_value:.0f} "
        f"gCO2/kWh). Net ~{net} kg/mo saved after a one-time ~{transit_kg} kg "
        f"transit for {dataset_gb} GB."
    )
    return action, {
        "plan": "relocate",
        "residency_locked": False,
        "relocate_to": g_region,
        "gross_relocate_kg": gross_savings,
        "transit_kg": transit_kg,
        "savings_kg": net,
    }


def _utilization_fraction(server):
    """Combine CPU and GPU utilization into one 0..1 load factor.

    For GPU instances the GPU dominates the power draw, so weight it heavily.
    """
    cpu = server.get("cpu_utilization", 0) / 100.0
    gpu = server.get("gpu_utilization", 0) / 100.0
    if server.get("instance_type", "").startswith("g5"):
        return 0.4 * cpu + 0.6 * gpu
    return cpu


def _power_fraction(util):
    """Non-linear server power curve (Fan et al.): f(u) = 2u - u^1.4, in [0,1]."""
    u = max(0.0, min(util, 1.0))
    return max(0.0, 2 * u - u ** POWER_CURVE_EXPONENT)


def estimate_power_kwh(server, include_pue=True):
    """Estimate this server's FACILITY energy use for the month, in kWh.

    IT power uses a non-linear curve:
        it_watts = max_watts * (idle_floor + (1 - idle_floor) * f(utilization))
    Facility power then applies the region's load-dependent PUE (cooling):
        facility_watts = it_watts * PUE(region, utilization)
    kWh = facility_watts * runtime_hours / 1000
    """
    max_watts = INSTANCE_MAX_WATTS.get(
        server.get("instance_type"), DEFAULT_MAX_WATTS
    )
    util = _utilization_fraction(server)
    it_watts = max_watts * (IDLE_POWER_FLOOR + (1 - IDLE_POWER_FLOOR) * _power_fraction(util))
    runtime = server.get("runtime_hours_this_month", 0)
    if include_pue:
        it_watts *= get_pue(server.get("region"), util)
    return it_watts * runtime / 1000.0


def compute_server_carbon(server):
    """Return a dict of energy/carbon/cost numbers for one server.

    This is the shared numeric basis for both the carbon agent's findings and
    the orchestrator's "$ saved + kg CO2e prevented" recommendations.
    """
    power_kwh = estimate_power_kwh(server)
    intensity = get_carbon_intensity(server["region"])
    carbon_kg = power_kwh * intensity.gco2_per_kwh / 1000.0
    pue = get_pue(server.get("region"), _utilization_fraction(server))
    return {
        "server_id": server["id"],
        "power_kwh": round(power_kwh, 1),
        "carbon_kg": round(carbon_kg, 1),
        "pue": pue,
        "intensity_gco2_kwh": intensity.gco2_per_kwh,
        "intensity_source": intensity.source,
        "intensity_label": intensity.label(),
        "monthly_cost_usd": server.get("monthly_cost_usd", 0),
    }


def is_deferrable(server):
    """True if the workload looks batch/deferrable (movable to a greener grid)."""
    role = server.get("role", "").lower()
    if any(k in role for k in DEFERRABLE_KEYWORDS):
        return True
    for task in server.get("scheduled_tasks", []):
        if any(k in task.get("task", "").lower() for k in DEFERRABLE_KEYWORDS):
            return True
    return False


def check_over_provisioning(server):
    """Flag a large instance running at very low CPU and GPU utilization."""
    max_watts = INSTANCE_MAX_WATTS.get(server.get("instance_type"), DEFAULT_MAX_WATTS)
    cpu = server.get("cpu_utilization", 0)
    gpu = server.get("gpu_utilization", 0)
    if max_watts >= LARGE_INSTANCE_WATTS and cpu < 10 and gpu < 10:
        carbon = compute_server_carbon(server)
        return make_finding(
            server, "OVER_PROVISIONED", "warning",
            f"{server['id']} is a large {server['instance_type']} running at "
            f"only {cpu}% CPU / {gpu}% GPU — paying "
            f"${server.get('monthly_cost_usd', 0)}/mo and emitting "
            f"~{carbon['carbon_kg']} kg CO2e/mo for near-idle compute. "
            f"Right-size to a smaller instance.",
            "check_over_provisioning", "carbon",
            carbon_kg=carbon["carbon_kg"],
            monthly_cost_usd=carbon["monthly_cost_usd"],
        )
    return None


def check_zombie(server):
    """Flag a server with ~zero utilization but high runtime (running for nothing)."""
    cpu = server.get("cpu_utilization", 0)
    gpu = server.get("gpu_utilization", 0)
    runtime = server.get("runtime_hours_this_month", 0)
    if cpu <= 2 and gpu <= 2 and runtime > 600:
        carbon = compute_server_carbon(server)
        return make_finding(
            server, "ZOMBIE", "warning",
            f"{server['id']} has run {runtime}h this month at ~0% utilization "
            f"({cpu}% CPU) — a zombie instance burning "
            f"${server.get('monthly_cost_usd', 0)}/mo and "
            f"~{carbon['carbon_kg']} kg CO2e/mo for no work.",
            "check_zombie", "carbon",
            carbon_kg=carbon["carbon_kg"],
            monthly_cost_usd=carbon["monthly_cost_usd"],
        )
    return None


def check_high_carbon_region(server):
    """Flag a deferrable workload on a high-carbon grid, with a transit- and
    sovereignty-aware greening plan (relocate vs time-shift)."""
    intensity = get_carbon_intensity(server["region"])
    if intensity.is_dirty and is_deferrable(server):
        carbon = compute_server_carbon(server)
        action, plan = _greening_plan(server, carbon, intensity)
        return make_finding(
            server, "HIGH_CARBON_REGION", "info",
            f"{server['id']} runs a deferrable workload in {server['region']} "
            f"({intensity.gco2_per_kwh:.0f} gCO2/kWh). {action}",
            "check_high_carbon_region", "carbon",
            carbon_kg=carbon["carbon_kg"], **plan,
        )
    return None


def check_good_vs_bad_carbon(server):
    """THE KEY ONE — distinguish legitimate heavy compute from likely-compromised.

    * High CPU + an active legitimate scheduled task -> "good carbon": the work
      is real; suggest routing to a greener region rather than killing it.
    * High CPU + no active scheduled task + high failed logins -> "bad carbon":
      the load has no legitimate source and the host is under attack -> likely
      compromised (crypto-mining). Coordinate with the cyber agent.
    """
    cpu = server.get("cpu_utilization", 0)
    if cpu <= 80:
        return None

    active_tasks = [t for t in server.get("scheduled_tasks", []) if t.get("active")]
    failed_logins = server.get("failed_login_attempts_last_hour", 0)
    carbon = compute_server_carbon(server)

    if not active_tasks:
        # BAD carbon — sustained high load with no legitimate cause is itself the
        # crypto-mining signature. Failed logins corroborate an active intrusion
        # but are NOT required: once the attacker is in, the miner keeps running
        # even after the brute force stops (so rotating creds alone won't clear
        # it — only killing the process does).
        attack_note = (
            f" and {failed_logins} failed logins" if failed_logins > 100 else ""
        )
        return make_finding(
            server, "BAD_CARBON_COMPROMISE", "critical",
            f"{server['id']} is pinned at {cpu}% CPU with NO active scheduled "
            f"task{attack_note} — unexplained, unauthorized compute consistent "
            f"with a hijacked crypto-mining host. Likely COMPROMISED: kill the "
            f"process (security + carbon + cost).",
            "check_good_vs_bad_carbon", "carbon",
            carbon_kg=carbon["carbon_kg"],
            monthly_cost_usd=carbon["monthly_cost_usd"],
            failed_logins=failed_logins,
            verdict="bad",
        )

    if active_tasks:
        # GOOD carbon — real work; green it rather than kill it.
        intensity = get_carbon_intensity(server["region"])
        action, plan = _greening_plan(server, carbon, intensity)
        return make_finding(
            server, "GOOD_CARBON", "info",
            f"{server['id']} is at {cpu}% CPU doing legitimate work "
            f"('{active_tasks[0]['task']}'). This is GOOD carbon — keep it "
            f"running. {action}",
            "check_good_vs_bad_carbon", "carbon",
            carbon_kg=carbon["carbon_kg"], verdict="good", **plan,
        )
    return None


CARBON_RULES = [
    check_over_provisioning,
    check_zombie,
    check_high_carbon_region,
    check_good_vs_bad_carbon,
]


def run_carbon_checks(server):
    """Run every carbon rule against one server. Returns a list of findings."""
    findings = [rule(server) for rule in CARBON_RULES]
    return [f for f in findings if f is not None]


if __name__ == "__main__":
    import json

    state = json.load(open("cloud_state.json"))
    gantt = state.get("project_gantt", {})
    for srv in state["servers"]:
        cyber = run_cyber_checks(srv, gantt)
        carbon = run_carbon_checks(srv)
        c = compute_server_carbon(srv)
        print(f"\n{srv['id']}  ({c['carbon_kg']} kg CO2e/mo, ${c['monthly_cost_usd']}/mo)")
        for f in cyber + carbon:
            print(f"  [{f['severity']:8}] {f['type']:22} {f['evidence'][:80]}")
