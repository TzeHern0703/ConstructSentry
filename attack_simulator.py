"""attack_simulator.py — Phase 2 of the demo: a LOCAL simulated attack.

This does NOT touch any real network or server. It rewrites `cloud_state.json`
so the target server carries the *signature* of a brute-force compromise that
has been hijacked for crypto-mining (PROJECT_SPEC Section 9, Phase 2):

  * failed_login_attempts_last_hour -> 450   (brute-force in progress)
  * cpu_utilization                -> 95     (pinned by unauthorized work)
  * gpu_utilization                -> 98     (GPU mining — drives the carbon spike)
  * scheduled_tasks                -> []     (no legitimate cause for the load)
  * status                         -> critical

The CPU/GPU spike makes the carbon number jump via the real power formula in
tools.py (not hardcoded), so the dashboard's carbon chart spikes on its own.
"""

from __future__ import annotations

import tools
from state_store import TARGET_ID, ensure_baseline, get_server, load_state, save_state

AGENT = "attack_simulator"


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def simulate_attack(emit=None, target_id=TARGET_ID):
    """Mutate the live state to carry an attack signature. Returns a summary."""
    # Capture the pristine baseline BEFORE we mutate, so remediation can restore.
    ensure_baseline()

    state = load_state()
    srv = get_server(state, target_id)
    if srv is None:
        raise ValueError(f"target server '{target_id}' not found")

    before = tools.compute_server_carbon(srv)
    _emit(emit, "reason",
          f"Injecting attack signature into {target_id} (LOCAL simulation — no "
          f"real network traffic).", "critical")

    srv["failed_login_attempts_last_hour"] = 450
    srv["cpu_utilization"] = 95
    srv["gpu_utilization"] = 98
    srv["scheduled_tasks"] = []
    srv["status"] = "critical"
    if 22 not in srv.get("open_ports", []):
        srv["open_ports"].append(22)
    srv["ssh_exposed"] = True

    save_state(state)
    after = tools.compute_server_carbon(srv)

    spike_pct = round(
        (after["carbon_kg"] - before["carbon_kg"]) / max(before["carbon_kg"], 0.1) * 100
    )
    _emit(emit, "observe",
          f"{target_id}: 450 failed logins, CPU 95%, GPU 98%, scheduled task "
          f"removed. Carbon {before['carbon_kg']} -> {after['carbon_kg']} "
          f"kg CO2e/mo (+{spike_pct}%).", "critical")

    return {
        "target": target_id,
        "before": before,
        "after": after,
        "carbon_spike_pct": spike_pct,
        "changes": {
            "failed_login_attempts_last_hour": 450,
            "cpu_utilization": 95,
            "gpu_utilization": 98,
            "scheduled_tasks": [],
            "status": "critical",
        },
        "state": state,
    }


if __name__ == "__main__":
    result = simulate_attack(emit=lambda t: print(f"  [{t['phase']:7}] {t['text']}"))
    print(f"\ncarbon spike: +{result['carbon_spike_pct']}% on {result['target']}")
