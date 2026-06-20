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


# Savings recovered by each lifecycle action, as a fraction of the server's
# full cost / carbon.
HIBERNATE_COST_RECOVERY = 0.85    # storage volume is still billed
HIBERNATE_CARBON_RECOVERY = 0.95  # only the idle disk still draws power

ACTION_LABEL = {
    "terminate": "Terminate",
    "hibernate": "Hibernate",
    "right_size": "Right-size",
    "scale_down": "Scale down",
    "scale_up": "Scale up",
    "route": "Relocate",
    "time_shift": "Time-shift",
    "isolate_restore": "Isolate & restore",
    "harden": "Harden config",
}


def _lifecycle_options(server, carbon):
    """Terminate vs Hibernate options for an idle/unneeded server — the choice
    changes the savings, so it's surfaced for the user to toggle."""
    sid = server["id"]
    cost = carbon["monthly_cost_usd"]
    co2 = carbon["carbon_kg"]
    return [
        {
            "type": "terminate", "label": "Terminate",
            "savings_usd": cost, "carbon_kg": round(co2, 1),
            "action": f"Terminate {sid} — delete the instance and its volumes "
                      f"(it isn't needed again).",
            "note": "Frees the most — but data is gone for good.",
        },
        {
            "type": "hibernate", "label": "Hibernate",
            "savings_usd": int(round(cost * HIBERNATE_COST_RECOVERY)),
            "carbon_kg": round(co2 * HIBERNATE_CARBON_RECOVERY, 1),
            "action": f"Hibernate {sid} — stop compute, keep the disk so it can "
                      f"wake on demand (small storage cost remains).",
            "note": "Disk kept, wakes in minutes — slightly less saved.",
        },
    ]


def _wins(security_line, savings_usd, carbon_kg):
    cost_line = f"Cost: ~${savings_usd:,}/mo saved" if savings_usd else "Cost: no change"
    carbon_line = f"Carbon: ~{carbon_kg} kg CO2e/mo cut" if carbon_kg else "Carbon: no change"
    return [security_line, cost_line, carbon_line]


def _recommend(category, server, carbon, finding_types, metrics):
    """Return (action, savings_usd, carbon_kg, wins, action_type, action_options).

    `action_type` is the recommended lifecycle action for this workload;
    `action_options` lists togglable alternatives (terminate vs hibernate) whose
    numbers differ, so the user can see which choice changes the result.
    """
    cost = carbon["monthly_cost_usd"]
    co2 = carbon["carbon_kg"]

    if category == "compromised_host":
        baseline = _baseline_carbon(server)
        prevented = round(max(co2 - baseline["carbon_kg"], 0.0), 1)
        action = ("Isolate the host, kill unauthorized processes, rotate "
                  "credentials, and restore its legitimate workload.")
        wins = [
            "Security: active breach contained, blueprint/asset data protected",
            f"Cost: ${cost:,}/mo of hijacked compute reclaimed for real work",
            f"Carbon: ~{prevented} kg CO2e/mo of zombie-mining emissions stopped",
        ]
        return action, cost, prevented, wins, "isolate_restore", []

    if category == "exposed_risk":
        fixes = []
        if "EXPOSED_SSH" in finding_types: fixes.append("close port 22 / restrict SSH")
        if "NO_ENCRYPTION" in finding_types: fixes.append("enable encryption at rest")
        if "WILDCARD_IAM" in finding_types: fixes.append("scope down IAM")
        if "NO_MFA" in finding_types: fixes.append("enforce MFA")
        if "STALE_CREDENTIALS" in finding_types: fixes.append("rotate credentials")
        action = "Harden configuration: " + ", ".join(fixes) + "."
        wins = ["Security: attack surface reduced before it can be exploited",
                "Cost: no change (server stays in service)", "Carbon: no change"]
        return action, 0, 0.0, wins, "harden", []

    if category == "orphaned_access":
        # Owner contract ended -> default Terminate; Hibernate offered as toggle.
        opts = _lifecycle_options(server, carbon)
        chosen = opts[0]  # terminate
        wins = _wins("Security: orphaned access path eliminated",
                     chosen["savings_usd"], chosen["carbon_kg"])
        return chosen["action"], chosen["savings_usd"], chosen["carbon_kg"], wins, "terminate", opts

    # pure_waste — carbon-aware autoscaling takes priority (it's SLO-driven).
    if "SCALE_DOWN" in finding_types:
        tgt = metrics.get("target_replicas"); lat = metrics.get("projected_latency_ms")
        slo = metrics.get("slo_ms")
        saved_usd = metrics.get("savings_usd", 0); saved_co2 = metrics.get("savings_kg", 0.0)
        action = (f"Scale down to {tgt} replicas — p95 stays ~{lat}ms, within the "
                  f"{slo}ms SLO. Carbon-aware right-sizing to actual load.")
        wins = _wins(f"Performance: ~{lat}ms < {slo}ms SLO (no breach)", saved_usd, saved_co2)
        return action, saved_usd, saved_co2, wins, "scale_down", []

    if "SCALE_UP" in finding_types:
        tgt = metrics.get("target_replicas"); lat = metrics.get("projected_latency_ms")
        slo = metrics.get("slo_ms"); cur_lat = metrics.get("latency_ms")
        extra_usd = metrics.get("extra_cost_usd", 0); extra_co2 = metrics.get("extra_carbon_kg", 0.0)
        action = (f"Scale up to {tgt} replicas to meet the {slo}ms latency SLO "
                  f"(p95 {cur_lat}ms → ~{lat}ms).")
        wins = [
            f"Performance: p95 {cur_lat}ms → ~{lat}ms, SLO restored",
            f"Cost: +${extra_usd:,}/mo (capacity to hold the SLO)",
            f"Carbon: +{extra_co2} kg CO2e/mo (the price of meeting the SLO)",
        ]
        return action, 0, 0.0, wins, "scale_up", []

    if "ZOMBIE" in finding_types:
        opts = _lifecycle_options(server, carbon)
        # Still contracted AND has a scheduled task => it'll be used again =>
        # Hibernate; otherwise Terminate. Both numbers offered for toggling.
        reusable = server.get("subcontractor_contract_active") and bool(server.get("scheduled_tasks"))
        default = "hibernate" if reusable else "terminate"
        chosen = next(o for o in opts if o["type"] == default)
        wins = _wins("Security: smaller footprint",
                     chosen["savings_usd"], chosen["carbon_kg"])
        return chosen["action"], chosen["savings_usd"], chosen["carbon_kg"], wins, default, opts

    if "OVER_PROVISIONED" in finding_types:
        saved_usd = int(round(cost * RIGHTSIZE_RECOVERY))
        saved_co2 = round(co2 * RIGHTSIZE_RECOVERY, 1)
        action = f"Right-size {server['id']} to a smaller instance matched to actual utilization."
        wins = _wins("Security: no change", saved_usd, saved_co2)
        return action, saved_usd, saved_co2, wins, "right_size", []

    # Greening a deferrable workload (GOOD_CARBON / HIGH_CARBON_REGION):
    # relocate vs time-shift, decided transit- and sovereignty-aware upstream.
    saved_co2 = metrics.get("savings_kg", round(co2 * 0.5, 1))
    relocate_to = metrics.get("relocate_to", "a greener region")
    transit_kg = metrics.get("transit_kg", 0)
    window = metrics.get("shift_window", "soon")
    spct = metrics.get("shift_pct", 0)
    best = metrics.get("forecast_best")
    win_phrase = (f"the greenest forecast window ({window}"
                  + (f", ~{best:.0f} gCO2/kWh" if best else "")
                  + f", −{spct}% vs now)")
    if metrics.get("plan") == "relocate":
        action = (f"Relocate to {relocate_to} — net carbon win after the one-time "
                  f"~{transit_kg} kg data-transit cost.")
        carbon_win = f"Carbon: ~{saved_co2} kg CO2e/mo net (after {transit_kg} kg transit)"
        action_type = "route"
    elif metrics.get("residency_locked"):
        action = (f"Data residency-locked to {metrics.get('residency')}: cannot move "
                  f"cross-border. Schedule it to {win_phrase}.")
        carbon_win = f"Carbon: ~{saved_co2} kg CO2e/mo by scheduling to {window} (no data moved)"
        action_type = "time_shift"
    else:
        action = (f"Transit carbon would cancel the relocation gain — schedule to "
                  f"{win_phrase} instead.")
        carbon_win = f"Carbon: ~{saved_co2} kg CO2e/mo by scheduling to {window}"
        action_type = "time_shift"
    wins = ["Security: no change", "Cost: ~$0/mo (same compute)", carbon_win]
    return action, 0, saved_co2, wins, action_type, []


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
        action, saved_usd, prevented_kg, wins, action_type, action_options = _recommend(
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
            "action_type": action_type,
            "action_label": ACTION_LABEL.get(action_type, action_type),
            "action_options": action_options,
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

# Findings are weighted by the asset's business criticality — a problem on a
# core BIM server matters far more than the same problem on disposable staging.
ASSET_WEIGHT = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5}

# A compromised CRITICAL asset is a single point of catastrophic risk: cap the
# whole score low regardless of how healthy the rest of the fleet looks, so a
# big fleet can't dilute one core breach into a falsely "passing" score.
COMPROMISED_CRITICAL_CEILING = 30


def summarize(state, results):
    """Build the headline numbers for the summary row / /api/summary.

    Returns: security_score (0-100), total carbon kg, total monthly cost,
    critical count, system status.
    """
    cyber = results["cyber"]["findings"]
    report = results["orchestrator"]["report"]
    incidents = results["orchestrator"]["incidents"]
    crit_of = {s["id"]: s.get("asset_criticality", "medium") for s in state["servers"]}

    # Asset-weighted penalty: weight each finding by its server's criticality.
    penalty = sum(
        SECURITY_PENALTY.get(f["severity"], 0)
        * ASSET_WEIGHT.get(crit_of.get(f["server_id"], "medium"), 1.0)
        for f in cyber
    )
    compromised = [i for i in incidents if i["category"] == "compromised_host"]
    if compromised:
        penalty += COMPROMISE_PENALTY
    security_score = max(0, round(100 - penalty))

    # Single-point-fatal: any compromised CRITICAL asset hard-caps the score.
    if any(crit_of.get(i["server_id"]) == "critical" for i in compromised):
        security_score = min(security_score, COMPROMISED_CRITICAL_CEILING)

    total_cost = sum(s.get("monthly_cost_usd", 0) for s in state["servers"])

    return {
        "security_score": security_score,
        "total_carbon_kg": results["carbon"]["totals"]["total_carbon_kg"],
        "total_cost_usd": total_cost,
        # The actionable money number: spend you can reclaim by acting on the
        # incidents (zombie shutdown + right-sizing + compromised-host recovery).
        "recoverable_usd": report["total_monthly_savings_usd"],
        "recoverable_carbon_kg": report["total_carbon_prevented_kg"],
        "critical_count": report["critical_count"],
        "compound_count": report["compound_count"],
        "system_status": report["system_status"],
        "intensity_source": results["carbon"]["totals"]["intensity_source"],
    }


def quick_results(state):
    """Detection-only pipeline (no agent narratives / no LLM) for the continuous
    monitor. Same result shape as run(), computed straight from tools.py so it's
    cheap to call every few seconds."""
    gantt = state.get("project_gantt", {})
    cyber, carbon_findings = [], []
    total_kwh = total_carbon = 0.0
    source = "fallback"
    for s in state["servers"]:
        cyber.extend(tools.run_cyber_checks(s, gantt))
        c = tools.compute_server_carbon(s)
        total_kwh += c["power_kwh"]
        total_carbon += c["carbon_kg"]
        if c["intensity_source"] == "live":
            source = "live"
        carbon_findings.extend(tools.run_carbon_checks(s))

    cyber_result = {
        "agent": "cyber", "findings": cyber, "narrative": None,
        "provider": "monitor",
        "critical_count": sum(f["severity"] == "critical" for f in cyber),
    }
    carbon_result = {
        "agent": "carbon", "findings": carbon_findings, "narrative": None,
        "totals": {
            "total_kwh": round(total_kwh, 1),
            "total_carbon_kg": round(total_carbon, 1),
            "intensity_source": source,
        },
        "provider": "monitor",
        "critical_count": sum(f["severity"] == "critical" for f in carbon_findings),
    }
    corr = correlate(state, cyber_result, carbon_result)
    return {"cyber": cyber_result, "carbon": carbon_result, "orchestrator": corr}


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
