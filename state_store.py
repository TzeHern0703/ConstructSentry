"""state_store.py — load/save the simulated environment + baseline management.

`cloud_state.json` is the live, mutable world. The attack mutates it; the
remediation restores it. To restore exactly, we keep a pristine snapshot
(`cloud_state.baseline.json`) captured the first time, before any mutation.

Shared by attack_simulator, remediation, main.py and api.py so there is one
definition of "the world" and how to reset it.
"""

from __future__ import annotations

import json
import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(BASE_DIR, "cloud_state.json")
BASELINE_PATH = os.path.join(BASE_DIR, "cloud_state.baseline.json")

# The server that becomes the attack target in the demo.
TARGET_ID = "bim-render-prod-02"


def load_state(path=STATE_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(state, path=STATE_PATH):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")


def ensure_baseline():
    """Capture the current state as the pristine baseline, once.

    Call this before the first mutation so the snapshot is the healthy seed.
    """
    if not os.path.exists(BASELINE_PATH):
        shutil.copyfile(STATE_PATH, BASELINE_PATH)


def load_baseline():
    ensure_baseline()
    return load_state(BASELINE_PATH)


def reset_to_baseline():
    """Overwrite the live state with the pristine baseline and return it."""
    baseline = load_baseline()
    save_state(baseline)
    return baseline


def get_server(state, server_id):
    for s in state["servers"]:
        if s["id"] == server_id:
            return s
    return None


if __name__ == "__main__":
    ensure_baseline()
    print("baseline exists:", os.path.exists(BASELINE_PATH))
    st = load_state()
    print("servers:", len(st["servers"]), "| target:", TARGET_ID)
