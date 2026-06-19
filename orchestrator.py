"""orchestrator.py — the correlation engine (THE STAR).

Takes the cyber agent's and carbon agent's findings and fuses them. The whole
pitch is here: when the SAME server shows up in BOTH the security findings and
the carbon findings, that's not two problems — it's ONE compound incident, and
one fix yields three wins (security + cost + carbon).

Pipeline (PROJECT_SPEC Section 6, orchestrator):
  1. Collect findings from both agents.
  2. Correlate by server_id -> compound incidents.
  3. Rank by combined severity:
        compromised host > orphaned access > exposed risk > pure waste.
  4. Produce a unified recommendation per incident, with concrete numbers
     ($ /mo saved + kg CO2e prevented).
  5. Emit a final report.
"""

from __future__ import annotations

import tools

AGENT = "orchestrator"

# Incident categories, highest priority first.
CATEGORY_ORDER = ["compromised_host", "orphaned_access", "exposed_risk", "pure_waste"]
CATEGORY_RANK = {c: i for i, c in enumerate(CATEGORY_ORDER)}

CATEGORY_LABEL = {
    "compromised_host": "COMPROMISED HOST",
    "orphaned_access": "ORPHANED ACCESS",
    "exposed_risk": "EXPOSED / MISCONFIGURED",
    "pure_waste": "CARBON WASTE",
}

# Finding types that indicate active compromise (top priority).
COMPROMISE_TYPES = {"BRUTE_FORCE", "BAD_CARBON_COMPROMISE"}

# Fraction of cost/carbon recovered by right-sizing an over-provisioned box.
RIGHTSIZE_RECOVERY = 0.70

# A legitimate "baseline" utilization used to estimate how much of a compromised
# host's current load is the hijack (vs. its normal work).
BASELINE_CPU = 15
BASELINE_GPU = 10


def _emit(emit, phase, text, severity="info"):
    if emit:
        emit({"agent": AGENT, "phase": phase, "text": text, "severity": severity})


def _server_index(state):
    return {s["id"]: s for s in state["servers"]}


def _categorize(finding_types):
    if finding_types & COMPROMISE_TYPES:
        return "compromised_host"
    if "ORPHANED_ACCESS" in finding_types:
        return "orphaned_access"
    # any cyber misconfig
    if finding_types & {
        "EXPOSED_SSH", "NO_ENCRYPTION", "WILDCARD_IAM", "NO_MFA", "STALE_CREDENTIALS"
    }:
        return "exposed_risk"
    return "pure_waste"


def _baseline_carbon(server):
    """Carbon if this host ran at a normal legitimate baseline utilization.

    Used to isolate the *extra* emissions caused by a hijack.
    """
    clone = dict(server)
    clone["cpu_utilization"] = min(server.get("cpu_utilization", 0), BASELINE_CPU)
    clone["gpu_utilization"] = min(server.get("gpu_utilization", 0), BASELINE_GPU)
    return tools.compute_server_carbon(clone)


def _recommend(category, server, carbon, finding_types, metrics):
    """Return (action, savings_usd, carbon_prevented_kg, wins[])."""
    cost = carbon["monthly_cost_usd"]
    co2 = carbon["carbon_kg"]
    wins = []

    if category == "compromised_host":
        # Legit asset hijacked for mining: isolate + restore, don't delete.
        # Carbon prevented = the extra emissions above the host's normal baseline.
        baseline = _baseline_carbon(server)
        prevented = round(max(co2 - baseline["carbon_kg"], 0.0), 1)
        action = (
            "Isolate the host, kill unauthorized processes, and rotate "
            "credentials. Restore it to its legitimate workload."
        )
        wins = [
            "Security: active breach contained, blueprint/asset data protected",
            f"Cost: ${cost:,}/mo of hijacked compute reclaimed for real work",
            f"Carbon: ~{prevented} kg CO2e/mo of zombie-mining emissions stopped",
        ]
        return action, cost, prevented, wins

    if category == "orphaned_access":
        # Subcontractor gone but server live: shut it down entirely.
        action = (
            f"Decommission this server — its owner's contract is inactive. "
            f"Revoke access and stop the instance."
        )
        wins = [
            "Security: orphaned access path eliminated",
            f"Cost: ${cost:,}/mo saved (instance no longer billed)",
            f"Carbon: ~{co2} kg CO2e/mo eliminated (instance powered off)",
        ]
        return action, cost, co2, wins

    if category == "exposed_risk":
        # Harden config; no compute is shut down, so no direct $/carbon savings.
        fixes = []
        if "EXPOSED_SSH" in finding_types:
            fixes.append("close port 22 / restrict SSH")
        if "NO_ENCRYPTION" in finding_types:
            fixes.append("enable encryption at rest")
        if "WILDCARD_IAM" in finding_types:
            fixes.append("scope down IAM")
        if "NO_MFA" in finding_types:
            fixes.append("enforce MFA")
        if "STALE_CREDENTIALS" in finding_types:
            fixes.append("rotate credentials")
        action = "Harden configuration: " + ", ".join(fixes) + "."
        wins = [
            "Security: attack surface reduced before it can be exploited",
            "Cost: no change (server stays in service)",
            "Carbon: no change",
        ]
        return action, 0, 0.0, wins

    # pure_waste
    if "ZOMBIE" in finding_types:
        action = "Decommission this zombie instance — it does no useful work."
        wins = [
            "Security: smaller footprint",
            f"Cost: ${cost:,}/mo saved (instance powered off)",
            f"Carbon: ~{co2} kg CO2e/mo eliminated",
        ]
        return action, cost, co2, wins

    if "OVER_PROVISIONED" in finding_types:
        saved_usd = int(round(cost * RIGHTSIZE_RECOVERY))
        saved_co2 = round(co2 * RIGHTSIZE_RECOVERY, 1)
        action = "Right-size to a smaller instance matched to actual utilization."
        wins = [
            "Security: no change",
            f"Cost: ~${saved_usd:,}/mo saved by right-sizing",
            f"Carbon: ~{saved_co2} kg CO2e/mo cut",
        ]
        return action, saved_usd, saved_co2, wins

    # relocate (GOOD_CARBON / HIGH_CARBON_REGION)
    relocate_to = metrics.get("relocate_to", "a greener region")
    saved_co2 = metrics.get("savings_kg", round(co2 * 0.5, 1))
    action = f"Route this deferrable workload to {relocate_to} (cleaner grid)."
    wins = [
        "Security: no change",
        "Cost: ~$0/mo (same compute, greener grid)",
        f"Carbon: ~{saved_co2} kg CO2e/mo cut by relocation",
    ]
    return action, 0, saved_co2, wins


def correlate(state, cyber_result, carbon_result, emit=None):
    """Fuse cyber + carbon findings into ranked, costed incidents."""
    servers = _server_index(state)
    cyber = cyber_result["findings"]
    carbon = carbon_result["findings"]

    _emit(emit, "reason",
          f"Correlating {len(cyber)} cyber + {len(carbon)} carbon findings by "
          f"server_id to find compound incidents.")

    # Group findings per server.
    grouped: dict[str, dict] = {}
    for f in cyber:
        grouped.setdefault(f["server_id"], {"cyber": [], "carbon": []})["cyber"].append(f)
    for f in carbon:
        grouped.setdefault(f["server_id"], {"cyber": [], "carbon": []})["carbon"].append(f)

    incidents = []
    for sid, group in grouped.items():
        server = servers.get(sid)
        if server is None:
            continue
        all_findings = group["cyber"] + group["carbon"]
        finding_types = {f["type"] for f in all_findings}
        is_compound = bool(group["cyber"]) and bool(group["carbon"])
        category = _categorize(finding_types)

        # Merge any metric hints (relocate target, savings) from findings.
        metrics = {}
        for f in all_findings:
            metrics.update(f.get("metrics", {}))

        carbon_nums = tools.compute_server_carbon(server)
        action, saved_usd, prevented_kg, wins = _recommend(
            category, server, carbon_nums, finding_types, metrics
        )

        severity = "critical" if any(
            f["severity"] == "critical" for f in all_findings
        ) else ("warning" if all_findings else "info")

        if is_compound:
            _emit(emit, "observe",
                  f"🔗 {sid} appears in BOTH cyber and carbon → COMPOUND "
                  f"INCIDENT ({CATEGORY_LABEL[category]}).",
                  severity)

        incidents.append({
            "server_id": sid,
            "category": category,
            "category_label": CATEGORY_LABEL[category],
            "severity": severity,
            "is_compound": is_compound,
            "cyber_findings": group["cyber"],
            "carbon_findings": group["carbon"],
            "finding_types": sorted(finding_types),
            "carbon": carbon_nums,
            "action": action,
            "monthly_savings_usd": saved_usd,
            "carbon_prevented_kg": prevented_kg,
            "wins": wins,
            "recommendation": _format_recommendation(action, saved_usd, prevented_kg),
        })

    # Rank: category priority, then critical-first, then biggest carbon impact.
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    incidents.sort(key=lambda inc: (
        CATEGORY_RANK[inc["category"]],
        sev_rank[inc["severity"]],
        -inc["carbon_prevented_kg"],
    ))

    report = _build_report(incidents)
    top = incidents[0] if incidents else None
    if top:
        _emit(emit, "reason",
              f"Top incident: {top['server_id']} ({top['category_label']}). "
              f"One fix = security + ${top['monthly_savings_usd']:,}/mo + "
              f"{top['carbon_prevented_kg']} kg CO2e.",
              top["severity"])

    return {
        "agent": AGENT,
        "incidents": incidents,
        "report": report,
        "compound_count": sum(1 for i in incidents if i["is_compound"]),
    }


def _format_recommendation(action, saved_usd, prevented_kg):
    money = f"${saved_usd:,}/mo saved" if saved_usd else "no extra cost"
    carbon = f"{prevented_kg} kg CO2e prevented" if prevented_kg else "no carbon change"
    return f"Action: {action} Result: {money} + {carbon}."


def _build_report(incidents):
    total_savings = sum(i["monthly_savings_usd"] for i in incidents)
    total_carbon = round(sum(i["carbon_prevented_kg"] for i in incidents), 1)
    critical = [i for i in incidents if i["severity"] == "critical"]
    compound = [i for i in incidents if i["is_compound"]]
    # System status is driven by an ACTIVE compromise, not by standing
    # advisories — so baseline (orphaned/waste/misconfig) reads HEALTHY and only
    # an active breach flips the UI to CRITICAL (FRONTEND_SPEC three states).
    compromised = any(i["category"] == "compromised_host" for i in incidents)
    return {
        "incident_count": len(incidents),
        "critical_count": len(critical),
        "compound_count": len(compound),
        "system_status": "CRITICAL" if compromised else "HEALTHY",
        "total_monthly_savings_usd": total_savings,
        "total_carbon_prevented_kg": total_carbon,
        "headline": (
            f"{len(incidents)} incidents · {len(compound)} compound "
            f"(security+carbon) · potential ${total_savings:,}/mo and "
            f"{total_carbon} kg CO2e/mo recovered."
        ),
    }


# Security-score penalties by severity (cyber findings only). Standing
# hygiene issues weigh modestly; an ACTIVE compromise tanks the score so the
# attack phase produces a dramatic, honest drop.
SECURITY_PENALTY = {"critical": 15, "warning": 2, "info": 1}
COMPROMISE_PENALTY = 25


def summarize(state, results):
    """Build the headline numbers for the summary row / /api/summary.

    Returns: security_score (0-100), total carbon kg, total monthly cost,
    critical count, system status.
    """
    cyber = results["cyber"]["findings"]
    report = results["orchestrator"]["report"]
    penalty = sum(SECURITY_PENALTY.get(f["severity"], 0) for f in cyber)
    if report["system_status"] == "CRITICAL":
        penalty += COMPROMISE_PENALTY
    security_score = max(0, 100 - penalty)

    total_cost = sum(s.get("monthly_cost_usd", 0) for s in state["servers"])

    return {
        "security_score": security_score,
        "total_carbon_kg": results["carbon"]["totals"]["total_carbon_kg"],
        "total_cost_usd": total_cost,
        "critical_count": report["critical_count"],
        "compound_count": report["compound_count"],
        "system_status": report["system_status"],
        "intensity_source": results["carbon"]["totals"]["intensity_source"],
    }


def run(state, emit=None):
    """Convenience: run both agents, then correlate. Returns the full result."""
    import carbon_agent
    import cyber_agent

    cyber_result = cyber_agent.scan(state, emit=emit)
    carbon_result = carbon_agent.scan(state, emit=emit)
    corr = correlate(state, cyber_result, carbon_result, emit=emit)
    return {
        "cyber": cyber_result,
        "carbon": carbon_result,
        "orchestrator": corr,
    }


if __name__ == "__main__":
    import json

    state = json.load(open("cloud_state.json"))
    result = run(state)
    corr = result["orchestrator"]
    print("\n========== ORCHESTRATOR REPORT ==========")
    print(corr["report"]["headline"])
    print(f"compound incidents: {corr['compound_count']}\n")
    for i, inc in enumerate(corr["incidents"], 1):
        flag = "🔗 COMPOUND " if inc["is_compound"] else ""
        print(f"{i}. [{inc['severity'].upper()}] {flag}{inc['server_id']} "
              f"({inc['category_label']})")
        print(f"   types: {', '.join(inc['finding_types'])}")
        for w in inc["wins"]:
            print(f"     · {w}")
        print()
