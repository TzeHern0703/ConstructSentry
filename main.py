"""main.py — the ConstructSentry CLI demo (PROJECT_SPEC Section 9).

Runs the three-phase live scenario in the terminal with rich:

  Phase 1  Baseline  : agents scan a calm fleet -> HEALTHY (green).
  Phase 2  Attack    : local attack signature injected -> CRITICAL (red),
                       carbon spikes, the compromised host is correlated.
  Phase 3  Heal       : one-click remediation -> HEALED (green returns),
                       final savings report.

The agents' Reason -> Act -> Observe thoughts stream live between the panels —
the "thinking" is the show. Detection logic and carbon data are real; the
environment and the attack are simulated.

Usage:
  python main.py            # interactive: press Enter between phases
  python main.py --auto     # auto-advance with short pauses
"""

from __future__ import annotations

import sys
import time

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import attack_simulator
import orchestrator
import remediation
import state_store
from llm import provider_label

console = Console()

AUTO = "--auto" in sys.argv

# Severity / agent colors.
SEV_COLOR = {"info": "cyan", "warning": "yellow", "critical": "bold red"}
AGENT_COLOR = {
    "cyber": "bright_blue",
    "carbon": "green",
    "orchestrator": "magenta",
    "attack_simulator": "red",
    "remediation": "bright_green",
    "investigator": "cyan",
}
PHASE_GLYPH = {"reason": "◆ think", "act": "▸ act  ", "observe": "● obs  "}


def _emit(event):
    """Live agent-thought printer for the SSE-equivalent CLI feed."""
    agent = event["agent"]
    phase = event["phase"]
    sev = event.get("severity", "info")
    ac = AGENT_COLOR.get(agent, "white")
    glyph = PHASE_GLYPH.get(phase, phase)
    label = Text()
    label.append(f"  {agent:<16}", style=ac)
    label.append(f"{glyph}  ", style="dim")
    label.append(event["text"], style=SEV_COLOR.get(sev) if sev == "critical" else None)
    console.print(label)
    if AUTO:
        time.sleep(0.04)


def pause(msg="Press Enter to continue"):
    if AUTO:
        time.sleep(1.2)
        return
    console.input(f"\n[dim]{msg}…[/dim]")


def banner(text, style):
    console.print()
    console.print(Panel(Align.center(Text(text, style=style)), style=style))


def render_summary(summary):
    status = summary["system_status"]
    color = "bold red" if status == "CRITICAL" else "bold green"
    t = Table.grid(expand=True)
    for _ in range(4):
        t.add_column(justify="center", ratio=1)
    t.add_row(
        _stat("SECURITY SCORE", f"{summary['security_score']}/100",
              "red" if summary["security_score"] < 70 else "green"),
        _stat("CARBON", f"{summary['total_carbon_kg']:.0f} kg CO2e/mo", "green"),
        _stat("MONTHLY COST", f"${summary['total_cost_usd']:,}", "cyan"),
        _stat("CRITICAL", str(summary["critical_count"]),
              "red" if summary["critical_count"] else "green"),
    )
    console.print(Panel(t, title=f"[{color}]SYSTEM: {status}[/{color}]",
                        border_style=color))


def _stat(label, value, color):
    g = Table.grid()
    g.add_column(justify="center")
    g.add_row(Text(value, style=f"bold {color}"))
    g.add_row(Text(label, style="dim"))
    return g


def render_servers(state, incidents):
    by_id = {i["server_id"]: i for i in incidents}
    table = Table(title="FLEET", expand=True, border_style="grey37")
    table.add_column("SERVER", style="bold")
    table.add_column("ROLE", style="dim")
    table.add_column("REGION", style="dim")
    table.add_column("CPU", justify="right")
    table.add_column("GPU", justify="right")
    table.add_column("STATUS", justify="center")
    for s in state["servers"]:
        inc = by_id.get(s["id"])
        st = s["status"]
        dot = {"healthy": "[green]●[/green]", "warning": "[yellow]●[/yellow]",
               "critical": "[bold red]●[/bold red]"}.get(st, "●")
        flag = " [bold red]⚠ COMPROMISED[/bold red]" if inc and inc["category"] == "compromised_host" else ""
        name = f"[bold red]{s['id']}[/bold red]" if st == "critical" else s["id"]
        table.add_row(name + flag, s["role"], s["region"],
                      f"{s['cpu_utilization']}%", f"{s['gpu_utilization']}%",
                      f"{dot} {st}")
    console.print(table)


def render_incidents(corr):
    incidents = corr["incidents"]
    if not incidents:
        console.print(Panel("No incidents.", border_style="green"))
        return
    console.print(f"\n[bold]INCIDENTS — ranked ({corr['compound_count']} compound)[/bold]")
    for i, inc in enumerate(incidents, 1):
        sev = inc["severity"]
        bc = SEV_COLOR.get(sev, "white")
        badge = " [black on red] 🔗 SECURITY + CARBON [/black on red]" if inc["is_compound"] else ""
        head = Text()
        head.append(f"{i}. {inc['server_id']} ", style=f"bold {bc}")
        head.append(f"[{inc['category_label']}]", style="dim")
        body = Text()
        body.append("\n   " + inc["action"], style="white")
        for w in inc["wins"]:
            body.append(f"\n     · {w}", style="dim")
        console.print(Panel(Text.assemble(head, body) + Text.from_markup(badge),
                            border_style=bc if sev != "info" else "grey37"))


def scan_and_render(state, title, title_style):
    banner(title, title_style)
    console.print("[dim]— agents reasoning live —[/dim]\n")
    results = orchestrator.run(state, emit=_emit)
    summary = orchestrator.summarize(state, results)
    console.print()
    render_summary(summary)
    render_servers(state, results["orchestrator"]["incidents"])
    render_incidents(results["orchestrator"])
    return results, summary


def main():
    console.clear()
    console.print(Panel(Align.center(Text.assemble(
        ("ConstructSentry\n", "bold white"),
        ("Dual-agent security + carbon monitoring for the construction cloud\n", "cyan"),
        ("In the cloud, a security vulnerability is almost always a carbon waste.", "italic dim"),
    )), border_style="bold cyan"))
    console.print(f"[dim]Reasoning engine: {provider_label()}  ·  "
                  f"Simulated construction-cloud environment · "
                  f"detection logic & carbon data are real[/dim]")

    # Start every run from the pristine baseline.
    state_store.ensure_baseline()
    state = state_store.reset_to_baseline()

    # --- Phase 1: Baseline ---
    scan_and_render(state, "PHASE 1 — BASELINE", "bold green")
    pause("Press Enter to SIMULATE ATTACK")

    # --- Phase 2: Attack ---
    banner("PHASE 2 — SIMULATING ATTACK", "bold red")
    attack_simulator.simulate_attack(emit=_emit)
    state = state_store.load_state()
    results, _ = scan_and_render(state, "PHASE 2 — UNDER ATTACK", "bold red")
    top = results["orchestrator"]["incidents"][0]
    console.print(Panel(
        Text.from_markup(
            f"[bold red]COMPOUND INCIDENT[/bold red] — {top['server_id']}: one "
            f"root cause, two crises. {top['recommendation']}"),
        border_style="bold red"))
    pause("Press Enter to HEAL")

    # --- Phase 3: Heal ---
    banner("PHASE 3 — ONE-CLICK REMEDIATION", "bold green")
    report = remediation.remediate(emit=_emit)
    state = state_store.load_state()
    scan_and_render(state, "PHASE 3 — HEALED", "bold green")
    console.print(Panel(Align.center(Text(report["headline"], style="bold green")),
                        title="[bold green]THREAT NEUTRALIZED[/bold green]",
                        border_style="bold green"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
