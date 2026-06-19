"""react_loop.py — the Reasoning -> Action -> Observation engine.

Drives an agent through visible ReAct cycles (PROJECT_SPEC Section 8):

  1. REASON  : the LLM sees the current cloud_state + goal and decides which
               detection tool to call next.
  2. ACT     : the chosen tool (a function from tools.py) is executed.
  3. OBSERVE : the tool result is fed back into the LLM context.
  4. repeat until the agent concludes or max_iterations is hit.

Every step is pushed through the ``emit`` callback as a {agent, phase, text,
severity} event, so the CLI and the dashboard SSE feed show the agent thinking
in real time. The detection tools are real (tools.py); the LLM only decides
what to look at and how to narrate it.

When no LLM is configured the loop runs a *scripted* ReAct trace — same
reason/act/observe rhythm, deterministic content — so the "thinking" demo
always works offline.
"""

from __future__ import annotations

import json

import tools
from llm import call_llm, llm_available, provider_label

MAX_ITERATIONS = 15


# ===========================================================================
# Tool registry — the actions the agent may take during the loop.
# Each entry: name -> (python callable(state, **input), anthropic tool schema)
# ===========================================================================

def _tool_list_servers(state, **_):
    return [
        {
            "id": s["id"],
            "role": s["role"],
            "region": s["region"],
            "cpu": s["cpu_utilization"],
            "gpu": s["gpu_utilization"],
            "failed_logins": s["failed_login_attempts_last_hour"],
            "ssh_exposed": s["ssh_exposed"],
            "contract_active": s["subcontractor_contract_active"],
        }
        for s in state["servers"]
    ]


def _find_server(state, server_id):
    for s in state["servers"]:
        if s["id"] == server_id:
            return s
    return None


def _tool_check_cyber(state, server_id=None, **_):
    srv = _find_server(state, server_id)
    if srv is None:
        return {"error": f"unknown server '{server_id}'"}
    return tools.run_cyber_checks(srv, state.get("project_gantt", {}))


def _tool_check_carbon(state, server_id=None, **_):
    srv = _find_server(state, server_id)
    if srv is None:
        return {"error": f"unknown server '{server_id}'"}
    carbon = tools.compute_server_carbon(srv)
    return {"carbon": carbon, "findings": tools.run_carbon_checks(srv)}


TOOL_SCHEMAS = [
    {
        "name": "list_servers",
        "description": "List all servers with key metrics (CPU, GPU, failed "
                       "logins, SSH exposure, contract status). Call first to "
                       "see the fleet.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_cyber",
        "description": "Run all security detection rules on one server and "
                       "return its findings.",
        "input_schema": {
            "type": "object",
            "properties": {"server_id": {"type": "string"}},
            "required": ["server_id"],
        },
    },
    {
        "name": "check_carbon",
        "description": "Estimate energy/carbon and run waste-detection rules on "
                       "one server.",
        "input_schema": {
            "type": "object",
            "properties": {"server_id": {"type": "string"}},
            "required": ["server_id"],
        },
    },
    {
        "name": "conclude",
        "description": "Finish the investigation with a short plain-language "
                       "summary of what was found.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]

TOOL_IMPLS = {
    "list_servers": _tool_list_servers,
    "check_cyber": _tool_check_cyber,
    "check_carbon": _tool_check_carbon,
}


SYSTEM_PROMPT = (
    "You are an investigation agent in ConstructSentry, monitoring a "
    "construction-tech cloud. Work in a Reason->Act->Observe loop: think about "
    "what to check, call ONE tool, observe the result, then continue. Start by "
    "listing servers, then investigate the suspicious ones (high failed "
    "logins, high CPU with no task, inactive contracts, exposed SSH). When you "
    "have a clear picture, call `conclude` with a short summary. Be decisive "
    "and do not exceed a handful of checks."
)


def _emit(emit, agent, phase, text, severity="info"):
    if emit:
        emit({"agent": agent, "phase": phase, "text": text, "severity": severity})


def _summarize_observation(name, result):
    """Compress a tool result into a one-line observation for the feed."""
    if name == "list_servers":
        return f"Inventoried {len(result)} servers."
    if name == "check_cyber":
        if isinstance(result, dict) and result.get("error"):
            return result["error"]
        if not result:
            return "No security findings."
        crit = [f for f in result if f["severity"] == "critical"]
        lead = crit[0] if crit else result[0]
        return f"{len(result)} finding(s); top: {lead['type']} ({lead['severity']})."
    if name == "check_carbon":
        findings = result.get("findings", [])
        kg = result.get("carbon", {}).get("carbon_kg")
        if not findings:
            return f"~{kg} kg CO2e/mo, no waste flags."
        crit = [f for f in findings if f["severity"] == "critical"]
        lead = crit[0] if crit else findings[0]
        return f"~{kg} kg CO2e/mo; {lead['type']} ({lead['severity']})."
    return json.dumps(result)[:160]


# ===========================================================================
# LLM-driven loop
# ===========================================================================

def _run_llm_loop(state, goal, agent, emit, max_iterations):
    findings = []
    messages = [{"role": "user", "content": f"Goal: {goal}\nBegin the investigation."}]
    conclusion = None

    for _ in range(max_iterations):
        resp = call_llm(messages, tools=TOOL_SCHEMAS, system=SYSTEM_PROMPT, max_tokens=900)

        if resp.text.strip():
            _emit(emit, agent, "reason", resp.text.strip())

        if not resp.wants_tool:
            conclusion = resp.text.strip() or conclusion
            break

        # Record the assistant turn (text + tool_use blocks) so the API stays
        # in a valid tool-use conversation state.
        assistant_blocks = []
        if resp.text.strip():
            assistant_blocks.append({"type": "text", "text": resp.text})
        for tc in resp.tool_calls:
            assistant_blocks.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_results = []
        stop = False
        for tc in resp.tool_calls:
            if tc.name == "conclude":
                conclusion = tc.input.get("summary", "")
                _emit(emit, agent, "reason", conclusion, "info")
                stop = True
                tool_results.append({
                    "type": "tool_result", "tool_use_id": tc.id,
                    "content": "Investigation concluded.",
                })
                continue

            impl = TOOL_IMPLS.get(tc.name)
            target = tc.input.get("server_id", "")
            _emit(emit, agent, "act",
                  f"{tc.name}({target})" if target else f"{tc.name}()")
            result = impl(state, **tc.input) if impl else {"error": "unknown tool"}

            # Accumulate real findings.
            if tc.name == "check_cyber" and isinstance(result, list):
                findings.extend(result)
            elif tc.name == "check_carbon" and isinstance(result, dict):
                findings.extend(result.get("findings", []))

            obs = _summarize_observation(tc.name, result)
            sev = "critical" if "critical" in obs else "info"
            _emit(emit, agent, "observe", obs, sev)

            tool_results.append({
                "type": "tool_result", "tool_use_id": tc.id,
                "content": json.dumps(result)[:2000],
            })

        messages.append({"role": "user", "content": tool_results})
        if stop:
            break

    return {"findings": findings, "conclusion": conclusion}


# ===========================================================================
# Scripted offline loop (same rhythm, deterministic content)
# ===========================================================================

def _run_scripted_loop(state, goal, agent, emit, max_iterations):
    findings = []

    _emit(emit, agent, "reason",
          "No external model configured — running the detection engine "
          "directly. First, inventory the fleet.")
    inventory = _tool_list_servers(state)
    _emit(emit, agent, "act", "list_servers()")
    _emit(emit, agent, "observe", _summarize_observation("list_servers", inventory))

    # Triage: prioritize servers that look suspicious so the trace reads like
    # an investigation rather than a brute sweep.
    def _suspicion(s):
        score = 0
        if s["failed_logins"] > 100:
            score += 100
        if s["cpu"] > 80:
            score += 40
        if not s["contract_active"]:
            score += 50
        if s["ssh_exposed"]:
            score += 5
        score += (s["cpu"] < 5) * 10  # idle waste
        return score

    ranked = sorted(inventory, key=_suspicion, reverse=True)
    checked = 0
    for entry in ranked:
        if checked >= max_iterations - 2:
            break
        sid = entry["id"]
        susp = _suspicion(entry)
        if susp == 0 and checked >= 4:
            continue  # stop spending steps on clean servers

        reason_bits = []
        if entry["failed_logins"] > 100:
            reason_bits.append(f"{entry['failed_logins']} failed logins")
        if entry["cpu"] > 80:
            reason_bits.append(f"{entry['cpu']}% CPU")
        if not entry["contract_active"]:
            reason_bits.append("inactive contract")
        if entry["cpu"] < 5:
            reason_bits.append("near-idle")
        why = ", ".join(reason_bits) if reason_bits else "routine check"
        _emit(emit, agent, "reason", f"Investigating {sid} ({why}).")

        cyber = _tool_check_cyber(state, sid)
        _emit(emit, agent, "act", f"check_cyber({sid})")
        sev = "critical" if any(f["severity"] == "critical" for f in cyber) else "info"
        _emit(emit, agent, "observe", _summarize_observation("check_cyber", cyber), sev)
        findings.extend(cyber)

        carbon = _tool_check_carbon(state, sid)
        _emit(emit, agent, "act", f"check_carbon({sid})")
        csev = "critical" if any(
            f["severity"] == "critical" for f in carbon["findings"]
        ) else "info"
        _emit(emit, agent, "observe", _summarize_observation("check_carbon", carbon), csev)
        findings.extend(carbon["findings"])

        checked += 1

    crit = [f for f in findings if f["severity"] == "critical"]
    conclusion = (
        f"Investigation complete: {len(findings)} findings across {checked} "
        f"servers, {len(crit)} critical."
    )
    _emit(emit, agent, "reason", conclusion, "critical" if crit else "info")
    return {"findings": findings, "conclusion": conclusion}


def run_react(state, goal="Find security and carbon problems across the fleet.",
              agent="investigator", emit=None, max_iterations=MAX_ITERATIONS):
    """Run the ReAct loop. Uses the LLM when available, otherwise a scripted
    deterministic trace. Returns {findings, conclusion, provider}.
    """
    _emit(emit, agent, "reason",
          f"Engine: {provider_label()}. Goal: {goal}")
    if llm_available():
        out = _run_llm_loop(state, goal, agent, emit, max_iterations)
    else:
        out = _run_scripted_loop(state, goal, agent, emit, max_iterations)
    out["provider"] = provider_label()
    return out


if __name__ == "__main__":
    state = json.load(open("cloud_state.json"))
    # Make the demo target look attacked so the trace finds the compromise.
    for s in state["servers"]:
        if s["id"] == "bim-render-prod-02":
            s["failed_login_attempts_last_hour"] = 450
            s["cpu_utilization"] = 95
            s["gpu_utilization"] = 98
            s["scheduled_tasks"] = []
    result = run_react(
        state, emit=lambda t: print(f"  [{t['phase']:7}] {t['text'][:95]}")
    )
    print(f"\nfindings: {len(result['findings'])} | provider: {result['provider']}")
