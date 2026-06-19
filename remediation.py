"""remediation.py — Phase 3 of the demo: one-click heal.

Restores the compromised host to its pristine baseline values (from the
snapshot captured by attack_simulator), simulating: isolate host, kill
unauthorized processes, roll back / rotate credentials (PROJECT_SPEC Section 9,
Phase 3).

Only the attack is undone — pre-existing standing issues (orphaned access,
over-provisioning, etc.) remain, because the heal protocol targets the active
breach, not the whole fleet. Returns a savings report with concrete numbers.
"""

from __future__ import annotations

import tools
from state_store import (
    TARGET_ID,
    get_server,
    load_baseline,
    load_state,
    save_state,
)

AGENT = "remediation"

# Fields restored to baseline when healing the compromised host.
RESTORE_FIELDS = [
    "failed_login_attempts_last_hour",
    "cpu_utilization",
    "gpu_utilization",
    "scheduled_tasks",
    "status",
    "open_ports",
    "ssh_exposed",
]


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def remediate(emit=None, target_id=TARGET_ID):
    """Restore the compromised host and report the savings."""
    state = load_state()
    srv = get_server(state, target_id)
    if srv is None:
        raise ValueError(f"target server '{target_id}' not found")

    before = tools.compute_server_carbon(srv)
    cost = srv.get("monthly_cost_usd", 0)

    _emit(emit, "reason",
          f"Heal protocol engaged on {target_id}: isolating host, killing "
          f"unauthorized processes, rolling back credentials.", "info")

    baseline = load_baseline()
    bsrv = get_server(baseline, target_id)

    _emit(emit, "act", f"Isolating {target_id} and terminating unauthorized compute.")
    for field in RESTORE_FIELDS:
        if bsrv is not None and field in bsrv:
            srv[field] = bsrv[field]

    # Credentials are rotated as part of the response.
    _emit(emit, "act", "Rotating credentials and revoking attacker sessions.")
    srv["last_credential_rotation_days"] = 0
    srv["failed_login_attempts_last_hour"] = 0

    save_state(state)
    after = tools.compute_server_carbon(srv)

    carbon_prevented = round(before["carbon_kg"] - after["carbon_kg"], 1)
    _emit(emit, "observe",
          f"{target_id} restored: carbon {before['carbon_kg']} -> "
          f"{after['carbon_kg']} kg CO2e/mo. Threat neutralized.", "info")

    report = {
        "target": target_id,
        "before": before,
        "after": after,
        "cost_avoided_usd": cost,
        "carbon_prevented_kg": carbon_prevented,
        "headline": (
            f"Threat neutralized on {target_id}. Data assets protected. "
            f"${cost:,}/mo of hijacked compute reclaimed. "
            f"{carbon_prevented} kg CO2e/mo of zombie-mining emissions "
            f"prevented from entering the atmosphere."
        ),
        "state": state,
    }
    _emit(emit, "reason", report["headline"], "info")
    return report


if __name__ == "__main__":
    result = remediate(emit=lambda t: print(f"  [{t['phase']:7}] {t['text']}"))
    print(f"\n{result['headline']}")
