"""cyber_agent.py — the security agent.

Scans every server with the deterministic cyber rules in tools.py, then uses
the LLM to rank the findings by danger and explain them in plain language. If
no LLM is configured it falls back to a deterministic narrative, so the agent
always produces a result (PROJECT_SPEC Section 6, Module B).

The agent emits "thoughts" (reason / act / observe) through an optional ``emit``
callback so the CLI and the dashboard SSE feed can show it reasoning live.
"""

from __future__ import annotations

import tools

AGENT = "cyber"

SYSTEM_PROMPT = (
    "You are the CYBER agent in ConstructSentry, a monitoring system for a "
    "construction-tech cloud (HILTI workloads: BIM rendering, Fieldwire, "
    "ON!Track, PROFIS, Nuron IoT). You receive raw security findings produced "
    "by deterministic detection rules. Your job: rank them by real-world danger "
    "(active compromise > orphaned subcontractor access > exposed/misconfig), "
    "and explain each in plain language a project manager would understand. Be "
    "concise and concrete. Never invent findings that are not in the input."
)


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def _deterministic_narrative(findings):
    """Plain-language ranking used when no LLM is available."""
    if not findings:
        return "No security findings. All servers within policy."
    order = {"critical": 0, "warning": 1, "info": 2}
    ranked = sorted(findings, key=lambda f: order.get(f["severity"], 3))
    lines = ["Security findings ranked by danger:"]
    for i, f in enumerate(ranked, 1):
        lines.append(f"{i}. [{f['severity'].upper()}] {f['evidence']}")
    return "\n".join(lines)


def _llm_narrative(findings):
    """Ask the LLM to rank + explain. Returns None on failure/offline."""
    from llm import complete

    payload = "\n".join(
        f"- {f['type']} ({f['severity']}) on {f['server_id']}: {f['evidence']}"
        for f in findings
    )
    prompt = (
        "Here are the raw security findings from this scan:\n\n"
        f"{payload}\n\n"
        "Rank them from most to least dangerous and explain each in one plain "
        "sentence. Call out any host that looks actively compromised. Keep the "
        "whole answer under 180 words."
    )
    return complete(prompt, system=SYSTEM_PROMPT)


def scan(state, emit=None):
    """Run the cyber scan over the whole environment.

    Returns: {agent, findings, narrative, provider, critical_count}.
    """
    from llm import provider_label

    servers = state["servers"]
    gantt = state.get("project_gantt", {})

    _emit(emit, "reason",
          f"Scanning {len(servers)} servers for exposure, weak auth, and "
          f"attack signatures.")

    findings = []
    for srv in servers:
        srv_findings = tools.run_cyber_checks(srv, gantt)
        if not srv_findings:
            continue
        for f in srv_findings:
            _emit(emit, "act",
                  f"Checked {srv['id']} -> {f['type']}", f["severity"])
            _emit(emit, "observe", f["evidence"], f["severity"])
        findings.extend(srv_findings)

    critical = [f for f in findings if f["severity"] == "critical"]

    if not findings:
        _emit(emit, "observe", "No security issues detected. Posture is clean.", "info")
    elif critical:
        _emit(emit, "reason",
              f"{len(critical)} CRITICAL security finding(s). Prioritizing "
              f"active threats.", "critical")

    narrative = _llm_narrative(findings) if findings else None
    if not narrative:
        narrative = _deterministic_narrative(findings)

    return {
        "agent": AGENT,
        "findings": findings,
        "narrative": narrative,
        "provider": provider_label(),
        "critical_count": len(critical),
    }


if __name__ == "__main__":
    import json

    state = json.load(open("cloud_state.json"))
    result = scan(state, emit=lambda t: print(f"  [{t['phase']:7}] {t['text'][:90]}"))
    print("\n--- NARRATIVE ---")
    print(result["narrative"])
    print(f"\nprovider: {result['provider']} | critical: {result['critical_count']}")
