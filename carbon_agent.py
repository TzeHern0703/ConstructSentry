"""carbon_agent.py — the carbon / energy agent.

For every server it estimates power and carbon (tools.compute_server_carbon),
then runs the deterministic waste rules. The headline capability is the
semantic "good carbon vs bad carbon" judgment (check_good_vs_bad_carbon): heavy
compute backed by a legitimate scheduled task is GOOD carbon (relocate, don't
kill); heavy compute with no legitimate cause + an attack signature is BAD
carbon -> likely a compromised crypto-mining host.

Uses the LLM to interpret the situation and make that reasoning visible
(PROJECT_SPEC Section 6, Module C). Falls back to deterministic reasoning when
no LLM is configured.
"""

from __future__ import annotations

import tools

AGENT = "carbon"

SYSTEM_PROMPT = (
    "You are the CARBON agent in ConstructSentry, watching a construction-tech "
    "cloud for energy and carbon waste. You receive per-server energy (kWh), "
    "carbon (kg CO2e), grid intensity, and waste findings. Your core skill is "
    "distinguishing GOOD carbon (legitimate heavy compute that should be routed "
    "to a greener grid) from BAD carbon (unexplained load with an attack "
    "signature -> a likely hijacked crypto-mining host that must be killed). "
    "Explain your judgment in plain language with concrete numbers. Be concise."
)


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def _deterministic_narrative(findings, totals):
    lines = [
        f"Fleet energy: ~{totals['total_kwh']:.0f} kWh/mo, "
        f"~{totals['total_carbon_kg']:.0f} kg CO2e/mo "
        f"(intensity: {totals['intensity_source']})."
    ]
    if not findings:
        lines.append("No carbon waste detected; utilization looks efficient.")
        return "\n".join(lines)
    order = {"critical": 0, "warning": 1, "info": 2}
    ranked = sorted(findings, key=lambda f: order.get(f["severity"], 3))
    lines.append("Carbon findings:")
    for i, f in enumerate(ranked, 1):
        lines.append(f"{i}. [{f['severity'].upper()}] {f['evidence']}")
    return "\n".join(lines)


def _llm_narrative(findings, totals):
    from llm import complete

    payload = "\n".join(
        f"- {f['type']} ({f['severity']}) on {f['server_id']}: {f['evidence']}"
        for f in findings
    )
    prompt = (
        f"Fleet totals: ~{totals['total_kwh']:.0f} kWh/mo and "
        f"~{totals['total_carbon_kg']:.0f} kg CO2e/mo.\n\n"
        f"Carbon findings from this scan:\n{payload}\n\n"
        "Summarize the carbon picture. Explicitly separate GOOD carbon "
        "(relocate to a greener grid) from BAD carbon (likely compromised host "
        "to kill). Keep numbers. Under 180 words."
    )
    return complete(prompt, system=SYSTEM_PROMPT)


def scan(state, emit=None):
    """Run the carbon scan over the whole environment.

    Returns: {agent, findings, narrative, totals, provider, critical_count}.
    """
    from llm import provider_label

    servers = state["servers"]

    _emit(emit, "reason",
          f"Estimating power and carbon for {len(servers)} servers, then "
          f"separating good carbon from bad carbon.")

    findings = []
    total_kwh = 0.0
    total_carbon = 0.0
    intensity_source = "fallback"

    for srv in servers:
        carbon = tools.compute_server_carbon(srv)
        total_kwh += carbon["power_kwh"]
        total_carbon += carbon["carbon_kg"]
        if carbon["intensity_source"] == "live":
            intensity_source = "live"

        srv_findings = tools.run_carbon_checks(srv)
        for f in srv_findings:
            verdict = f["metrics"].get("verdict")
            tag = f" [{verdict.upper()} CARBON]" if verdict else ""
            _emit(emit, "act",
                  f"Assessed {srv['id']} -> {f['type']}{tag}", f["severity"])
            _emit(emit, "observe", f["evidence"], f["severity"])
        findings.extend(srv_findings)

    totals = {
        "total_kwh": round(total_kwh, 1),
        "total_carbon_kg": round(total_carbon, 1),
        "intensity_source": intensity_source,
    }

    critical = [f for f in findings if f["severity"] == "critical"]
    if critical:
        _emit(emit, "reason",
              f"Detected BAD carbon: {len(critical)} host(s) burning energy "
              f"with no legitimate cause. Flagging as likely compromised.",
              "critical")

    narrative = _llm_narrative(findings, totals) if findings else None
    if not narrative:
        narrative = _deterministic_narrative(findings, totals)

    return {
        "agent": AGENT,
        "findings": findings,
        "narrative": narrative,
        "totals": totals,
        "provider": provider_label(),
        "critical_count": len(critical),
    }


if __name__ == "__main__":
    import json

    state = json.load(open("cloud_state.json"))
    result = scan(state, emit=lambda t: print(f"  [{t['phase']:7}] {t['text'][:90]}"))
    print("\n--- NARRATIVE ---")
    print(result["narrative"])
    print(f"\ntotals: {result['totals']} | provider: {result['provider']}")
