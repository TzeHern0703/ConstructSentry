"""_env.py — minimal .env loader (no external dependency).

Import this module for its side effect: it reads a local ``.env`` file (if
present) and populates os.environ, so ELECTRICITY_MAPS_API_KEY / ANTHROPIC_API_KEY
/ GEMINI_API_KEY are available to the CLI and the API without exporting them by
hand. Existing environment variables always win (setdefault).
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | None = None) -> None:
    p = Path(path) if path else Path(__file__).with_name(".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
