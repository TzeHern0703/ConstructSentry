"""remediation.py — Phase 3: one-click heal, modelled as cause-and-effect.

Rather than blindly overwriting the compromised host with baseline values and
asserting "fixed", remediation runs discrete response actions, each of which
addresses a *specific* symptom — and crucially, the CPU/GPU only come down when
the unauthorized process is actually killed. It then RE-SCANS to verify the
threat is gone instead of assuming it (PROJECT_SPEC Section 9, Phase 3).

Response steps (each maps to a real cloud IR action):
  * isolate            — network-isolate the host (close SSH / port 22)
  * kill_process       — terminate the unauthorized mining process; THIS is what
                         drops CPU/GPU back to the legitimate baseline and
                         restores the real workload
  * rotate_credentials — rotate creds and clear the attacker's login attempts

Passing a subset of steps reproduces the real-world failure mode: rotate
credentials but skip kill_process and the host stays pinned at 95% CPU — so
verification fails and the system says so.
"""

from __future__ import annotations

import random

import tools
import state_store
from state_store import TARGET_ID, get_server, load_baseline, load_state, save_state

AGENT = "remediation"

ALL_STEPS = ["isolate", "kill_process", "rotate_credentials"]


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def _legit_utilization(nominal):
    """A plausible *current* utilization for the restored legitimate workload.

    After the miner is killed, utilization is whatever the real workload happens
    to be drawing now — not a perfect replay of a historical snapshot. We center
    on the workload's nominal level and add live jitter so the recovered state
    is realistic rather than 'frozen-in-time'.
    """
    if not nominal:
        return nominal
    return max(0, round(nominal * random.uniform(0.8, 1.2)))


def _apply_step(step, srv, baseline_srv):
    """Apply one response action by restoring the fields it governs."""
    if step == "isolate":
        srv["ssh_exposed"] = baseline_srv["ssh_exposed"]
        srv["open_ports"] = list(baseline_srv["open_ports"])
    elif step == "kill_process":
        # Killing the mining daemon frees the compute; the server then settles
        # back into its LEGITIMATE workload's operating range (config restored,
        # utilization a live value near nominal — not a static snapshot replay).
        srv["scheduled_tasks"] = baseline_srv["scheduled_tasks"]
        srv["cpu_utilization"] = _legit_utilization(baseline_srv["cpu_utilization"])
        srv["gpu_utilization"] = _legit_utilization(baseline_srv["gpu_utilization"])
        srv["status"] = baseline_srv["status"]
    elif step == "rotate_credentials":
        srv["failed_login_attempts_last_hour"] = 0
        srv["last_credential_rotation_days"] = 0


def remediate(emit=None, target_id=TARGET_ID, steps=None):
    """Run the heal protocol, then VERIFY by re-scanning the target.

    Returns a report including which steps ran, whether verification passed, and
    any residual critical findings.
    """
    steps = steps or ALL_STEPS
    # Atomic read-modify-write+verify so a concurrent monitor sweep can't
    # interleave between the fix and the verification.
    with state_store.transaction():
        state = load_state()
        srv = get_server(state, target_id)
        if srv is None:
            raise ValueError(f"target server '{target_id}' not found")

        before = tools.compute_server_carbon(srv)
        cost = srv.get("monthly_cost_usd", 0)
        baseline = load_baseline()
        bsrv = get_server(baseline, target_id)

        _emit(emit, "reason",
              f"Heal protocol on {target_id}: running {', '.join(steps)}.", "info")
        for step in steps:
            _emit(emit, "act", f"{step.replace('_', ' ')} on {target_id}.")
            _apply_step(step, srv, bsrv)

        save_state(state)
        after = tools.compute_server_carbon(srv)

        # VERIFY — re-scan the target instead of asserting success.
        _emit(emit, "act", f"Re-scanning {target_id} to verify remediation.")
        residual = (
            tools.run_cyber_checks(srv, state.get("project_gantt", {}))
            + tools.run_carbon_checks(srv)
        )
    residual_critical = [f for f in residual if f["severity"] == "critical"]
    verified = not residual_critical

    carbon_prevented = round(before["carbon_kg"] - after["carbon_kg"], 1)

    if verified:
        headline = (
            f"Verified: threat on {target_id} neutralized. Data assets "
            f"protected. ${cost:,}/mo of hijacked compute reclaimed. "
            f"{carbon_prevented} kg CO2e/mo of zombie-mining emissions prevented."
        )
        _emit(emit, "observe",
              f"Verification PASSED — {target_id} clean. Carbon "
              f"{before['carbon_kg']} -> {after['carbon_kg']} kg CO2e/mo.", "info")
    else:
        types = ", ".join(f["type"] for f in residual_critical)
        headline = (
            f"Remediation INCOMPLETE on {target_id}: still critical ({types}). "
            f"The unauthorized load is still running — credential rotation alone "
            f"does not stop it; the process must be killed."
        )
        _emit(emit, "observe",
              f"Verification FAILED — {target_id} still critical: {types}.",
              "critical")

    _emit(emit, "reason", headline, "info" if verified else "critical")

    return {
        "target": target_id,
        "steps_applied": steps,
        "verified": verified,
        "residual_critical": [f["type"] for f in residual_critical],
        "before": before,
        "after": after,
        "cost_avoided_usd": cost if verified else 0,
        "carbon_prevented_kg": carbon_prevented,
        "headline": headline,
        "state": state,
    }


if __name__ == "__main__":
    import attack_simulator
    import state_store

    print("=== FULL HEAL ===")
    state_store.reset_to_baseline()
    attack_simulator.simulate_attack()
    r = remediate(emit=lambda t: print(f"  [{t['phase']:7}] {t['text']}"))
    print("verified:", r["verified"], "\n")

    print("=== PARTIAL HEAL (rotate creds only — should FAIL verification) ===")
    state_store.reset_to_baseline()
    attack_simulator.simulate_attack()
    r = remediate(steps=["rotate_credentials"],
                  emit=lambda t: print(f"  [{t['phase']:7}] {t['text']}"))
    print("verified:", r["verified"], "| residual:", r["residual_critical"])
    state_store.reset_to_baseline()
