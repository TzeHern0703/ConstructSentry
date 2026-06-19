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

from carbon_data import get_carbon_intensity, greenest_region

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

# Instances at or above this peak draw are considered "large" for the
# over-provisioning check.
LARGE_INSTANCE_WATTS = 600

# Role keywords that indicate a deferrable / batch workload (can be moved to a
# greener region or scheduled when the grid is clean).
DEFERRABLE_KEYWORDS = ("render", "archive", "calc", "sync", "batch", "reconcil")


def _utilization_fraction(server):
    """Combine CPU and GPU utilization into one 0..1 load factor.

    For GPU instances the GPU dominates the power draw, so weight it heavily.
    """
    cpu = server.get("cpu_utilization", 0) / 100.0
    gpu = server.get("gpu_utilization", 0) / 100.0
    if server.get("instance_type", "").startswith("g5"):
        return 0.4 * cpu + 0.6 * gpu
    return cpu


def estimate_power_kwh(server):
    """Estimate this server's energy use for the month, in kWh.

    power = max_watts * (idle_floor + (1 - idle_floor) * utilization)
    kWh   = power_watts * runtime_hours / 1000
    """
    max_watts = INSTANCE_MAX_WATTS.get(
        server.get("instance_type"), DEFAULT_MAX_WATTS
    )
    util = _utilization_fraction(server)
    power_watts = max_watts * (IDLE_POWER_FLOOR + (1 - IDLE_POWER_FLOOR) * util)
    runtime = server.get("runtime_hours_this_month", 0)
    return power_watts * runtime / 1000.0


def compute_server_carbon(server):
    """Return a dict of energy/carbon/cost numbers for one server.

    This is the shared numeric basis for both the carbon agent's findings and
    the orchestrator's "$ saved + kg CO2e prevented" recommendations.
    """
    power_kwh = estimate_power_kwh(server)
    intensity = get_carbon_intensity(server["region"])
    carbon_kg = power_kwh * intensity.gco2_per_kwh / 1000.0
    return {
        "server_id": server["id"],
        "power_kwh": round(power_kwh, 1),
        "carbon_kg": round(carbon_kg, 1),
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
    """Flag a deferrable workload running on a high-carbon grid."""
    intensity = get_carbon_intensity(server["region"])
    if intensity.is_dirty and is_deferrable(server):
        g_region, g_value = greenest_region()
        carbon = compute_server_carbon(server)
        # Carbon if the same energy ran on the greenest grid.
        greener_kg = round(carbon["power_kwh"] * g_value / 1000.0, 1)
        savings_kg = round(carbon["carbon_kg"] - greener_kg, 1)
        return make_finding(
            server, "HIGH_CARBON_REGION", "info",
            f"{server['id']} runs a deferrable workload in {server['region']} "
            f"({intensity.gco2_per_kwh:.0f} gCO2/kWh). Relocating to "
            f"{g_region} ({g_value:.0f} gCO2/kWh) would cut "
            f"~{savings_kg} kg CO2e/mo with no loss of capacity.",
            "check_high_carbon_region", "carbon",
            carbon_kg=carbon["carbon_kg"],
            relocate_to=g_region,
            savings_kg=savings_kg,
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

    if not active_tasks and failed_logins > 100:
        # BAD carbon — high load with no legitimate cause + attack signature.
        return make_finding(
            server, "BAD_CARBON_COMPROMISE", "critical",
            f"{server['id']} is pinned at {cpu}% CPU with NO active scheduled "
            f"task and {failed_logins} failed logins — this is unexplained, "
            f"unauthorized compute consistent with a hijacked crypto-mining "
            f"host. Likely COMPROMISED: kill it (security + carbon + cost).",
            "check_good_vs_bad_carbon", "carbon",
            carbon_kg=carbon["carbon_kg"],
            monthly_cost_usd=carbon["monthly_cost_usd"],
            failed_logins=failed_logins,
            verdict="bad",
        )

    if active_tasks:
        # GOOD carbon — real work; relocate rather than kill.
        g_region, g_value = greenest_region()
        intensity = get_carbon_intensity(server["region"])
        greener_kg = round(carbon["power_kwh"] * g_value / 1000.0, 1)
        savings_kg = round(carbon["carbon_kg"] - greener_kg, 1)
        return make_finding(
            server, "GOOD_CARBON", "info",
            f"{server['id']} is at {cpu}% CPU doing legitimate work "
            f"('{active_tasks[0]['task']}'). This is GOOD carbon — keep it "
            f"running, but it sits on a {intensity.gco2_per_kwh:.0f} gCO2/kWh "
            f"grid. Routing to {g_region} would save ~{savings_kg} kg CO2e/mo.",
            "check_good_vs_bad_carbon", "carbon",
            carbon_kg=carbon["carbon_kg"],
            relocate_to=g_region,
            savings_kg=savings_kg,
            verdict="good",
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
