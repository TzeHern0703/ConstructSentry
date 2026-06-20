"""carbon_data.py — carbon intensity lookup for ConstructSentry.

Tries the real Electricity Maps API first; falls back to a hardcoded table of
realistic gCO2eq/kWh values if no API key is configured or the call fails.

Every lookup returns *both* the value and its source ("live" | "fallback") so
the rest of the system can be honest in the UI about where the number came
from (PROJECT_SPEC Section 7).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import _env  # noqa: F401  (loads .env into os.environ on import)

try:  # requests is optional — fallback works without any network stack
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


# --- Configuration ---------------------------------------------------------

ELECTRICITY_MAPS_URL = "https://api.electricitymap.org/v3/carbon-intensity/latest"
ELECTRICITY_MAPS_HISTORY_URL = "https://api.electricitymap.org/v3/carbon-intensity/history"
ELECTRICITY_MAPS_FORECAST_URL = "https://api.electricitymap.org/v3/carbon-intensity/forecast"

# Read the API key from the environment so we never hardcode secrets.
API_KEY = os.environ.get("ELECTRICITY_MAPS_API_KEY", "").strip()

# How long to wait on the live API before giving up and using the fallback.
REQUEST_TIMEOUT_SECONDS = 4


# Cloud region -> Electricity Maps zone code.
REGION_TO_ZONE = {
    "ap-southeast-1": "SG",      # Singapore
    "ap-southeast-3": "ID",      # Indonesia
    "us-east-1": "US-MIDA-PJM",  # N. Virginia (PJM grid)
    "eu-north-1": "SE",          # Sweden
    "eu-west-1": "IE",           # Ireland
    "ca-central-1": "CA-QC",     # Canada (Quebec, hydro)
}


# Fallback table (gCO2eq/kWh, realistic approximate values).
CARBON_INTENSITY_FALLBACK = {
    "ap-southeast-1": 408,   # Singapore (gas-heavy)
    "ap-southeast-3": 650,   # Indonesia (coal-heavy)
    "us-east-1": 367,        # N. Virginia
    "eu-north-1": 30,        # Sweden (hydro/nuclear, very clean)
    "eu-west-1": 290,        # Ireland
    "ca-central-1": 120,     # Canada (hydro)
}

# Used when a region is entirely unknown to us — a conservative global-ish mean.
DEFAULT_INTENSITY = 475


# Datacenter cooling overhead (PUE — Power Usage Effectiveness) by region.
# Total facility power = IT power x PUE. Hot/humid climates spend far more energy
# on cooling than cold ones (free cooling), so the SAME server emits more carbon
# in Singapore than in Sweden even before grid intensity is considered.
REGION_PUE = {
    "ap-southeast-1": 1.50,   # Singapore — hot, humid
    "ap-southeast-3": 1.55,   # Indonesia — hot, humid
    "us-east-1": 1.20,        # N. Virginia — temperate
    "eu-west-1": 1.15,        # Ireland — cool maritime
    "eu-north-1": 1.10,       # Sweden — cold, free cooling
    "ca-central-1": 1.10,     # Canada (Quebec) — cold
}
DEFAULT_PUE = 1.40

# PUE is not constant: as IT load rises the chillers work harder, so effective
# PUE climbs with utilization. This is the "cooling penalty at high load" a
# static average misses.
COOLING_LOAD_SENSITIVITY = 0.12


def get_pue(region: str, utilization: float = 0.0) -> float:
    """Effective PUE for a region at a given 0..1 IT utilization."""
    base = REGION_PUE.get(region, DEFAULT_PUE)
    u = max(0.0, min(utilization, 1.0))
    return round(base + COOLING_LOAD_SENSITIVITY * u, 3)


@dataclass
class CarbonIntensity:
    """Result of a carbon-intensity lookup."""

    region: str
    zone: str | None
    gco2_per_kwh: float
    source: str  # "live" | "fallback"

    @property
    def is_clean(self) -> bool:
        """Roughly, a low-carbon grid (hydro/nuclear-heavy)."""
        return self.gco2_per_kwh <= 150

    @property
    def is_dirty(self) -> bool:
        """Roughly, a high-carbon grid (coal/gas-heavy) — defer/relocate here."""
        return self.gco2_per_kwh >= 400

    def label(self) -> str:
        """Human-readable source label for the UI/CLI (honesty requirement)."""
        if self.source == "live":
            return f"{self.gco2_per_kwh:.0f} gCO2/kWh (live · Electricity Maps)"
        return f"{self.gco2_per_kwh:.0f} gCO2/kWh (fallback table)"


# Small in-process cache so repeated lookups during a scan don't re-hit the API.
_cache: dict[str, CarbonIntensity] = {}


def _fetch_live(region: str, zone: str) -> CarbonIntensity | None:
    """Attempt a live Electricity Maps lookup. Returns None on any failure."""
    if not API_KEY or requests is None:
        return None
    try:
        resp = requests.get(
            ELECTRICITY_MAPS_URL,
            params={"zone": zone},
            headers={"auth-token": API_KEY},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        value = data.get("carbonIntensity")
        if value is None:
            return None
        return CarbonIntensity(
            region=region,
            zone=zone,
            gco2_per_kwh=float(value),
            source="live",
        )
    except Exception:
        # Any network/parse error -> caller falls back to the table.
        return None


def get_carbon_intensity(region: str, use_cache: bool = True) -> CarbonIntensity:
    """Return the carbon intensity for a cloud region.

    Tries the live Electricity Maps API; on any failure (no key, network
    error, unknown zone) returns the fallback-table value. Always succeeds.
    """
    if use_cache and region in _cache:
        return _cache[region]

    zone = REGION_TO_ZONE.get(region)

    result: CarbonIntensity | None = None
    if zone is not None:
        result = _fetch_live(region, zone)

    if result is None:
        value = CARBON_INTENSITY_FALLBACK.get(region, DEFAULT_INTENSITY)
        result = CarbonIntensity(
            region=region,
            zone=zone,
            gco2_per_kwh=float(value),
            source="fallback",
        )

    if use_cache:
        _cache[region] = result
    return result


def greenest_region() -> tuple[str, float]:
    """Return the (region, intensity) of the cleanest known grid.

    Used by the carbon agent to suggest relocating deferrable workloads.
    """
    region = min(CARBON_INTENSITY_FALLBACK, key=CARBON_INTENSITY_FALLBACK.get)
    return region, float(CARBON_INTENSITY_FALLBACK[region])


def clear_cache() -> None:
    """Reset the in-process cache (useful for tests / re-scans)."""
    _cache.clear()
    _shift_cache.clear()
    _forecast_cache.clear()


# --- Carbon forecast (predictive, temporal scheduling) ---------------------

@dataclass
class CarbonForecast:
    region: str
    source: str                 # "live" | "fallback"
    now: float                  # current intensity
    points: list                # [{"offset_h": int, "intensity": float}]
    best_offset_h: int          # hours from now to the greenest window
    best_intensity: float
    reduction_pct: int          # how much cleaner the best window is vs now

    def window_label(self) -> str:
        if self.best_offset_h <= 0:
            return "now"
        return f"+{self.best_offset_h}h"


_forecast_cache: dict[str, CarbonForecast] = {}
FORECAST_HOURS = 24


def _fallback_forecast(region: str) -> CarbonForecast:
    """Synthesize a realistic daily curve when the API is unavailable: grids are
    cleaner overnight (lower demand) — dips around 03:00, peaks late afternoon."""
    import datetime
    base = CARBON_INTENSITY_FALLBACK.get(region, DEFAULT_INTENSITY)
    hour_now = datetime.datetime.now().hour
    pts = []
    for h in range(FORECAST_HOURS):
        clock = (hour_now + h) % 24
        # ±22% daily swing, minimum near 03:00.
        factor = 1 - 0.22 * math.cos((clock - 15) / 24 * 2 * math.pi)
        pts.append({"offset_h": h, "intensity": round(base * factor)})
    now_val = pts[0]["intensity"]
    best = min(pts, key=lambda p: p["intensity"])
    red = round((now_val - best["intensity"]) / now_val * 100) if now_val else 0
    return CarbonForecast(region, "fallback", now_val, pts,
                          best["offset_h"], best["intensity"], red)


def get_carbon_forecast(region: str, use_cache: bool = True) -> CarbonForecast:
    """Next-24h grid carbon forecast for a region, with the greenest upcoming
    window — the basis for scheduling deferrable work to when the grid is clean."""
    if use_cache and region in _forecast_cache:
        return _forecast_cache[region]

    result = None
    zone = REGION_TO_ZONE.get(region)
    if API_KEY and requests is not None and zone:
        try:
            resp = requests.get(
                ELECTRICITY_MAPS_FORECAST_URL,
                params={"zone": zone},
                headers={"auth-token": API_KEY},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            raw = resp.json().get("forecast", [])
            vals = [r["carbonIntensity"] for r in raw
                    if r.get("carbonIntensity") is not None][:FORECAST_HOURS]
            if len(vals) >= 4:
                pts = [{"offset_h": i, "intensity": round(v)} for i, v in enumerate(vals)]
                now_val = pts[0]["intensity"]
                best = min(pts, key=lambda p: p["intensity"])
                red = round((now_val - best["intensity"]) / now_val * 100) if now_val else 0
                result = CarbonForecast(region, "live", now_val, pts,
                                        best["offset_h"], best["intensity"], red)
        except Exception:
            result = None

    if result is None:
        result = _fallback_forecast(region)

    if use_cache:
        _forecast_cache[region] = result
    return result


# Fallback intraday swing when the history API isn't available — clearly labeled.
DEFAULT_SHIFT_FRACTION = 0.15

_shift_cache: dict[str, tuple[float, str]] = {}


def get_intraday_shift(region: str, use_cache: bool = True) -> tuple[float, str]:
    """Achievable carbon saving from time-shifting a deferrable job to the
    greenest hour IN-REGION, derived from the real last-24h grid curve:

        fraction = (current_intensity - min_24h) / current_intensity

    Returns (fraction, source) where source is "live" | "fallback". This
    replaces the old hardcoded 20% with data — the swing differs a lot by grid
    (hydro-heavy Canada is flat; coal/solar mixes swing hard).
    """
    if use_cache and region in _shift_cache:
        return _shift_cache[region]

    result = (DEFAULT_SHIFT_FRACTION, "fallback")
    zone = REGION_TO_ZONE.get(region)
    if API_KEY and requests is not None and zone:
        try:
            resp = requests.get(
                ELECTRICITY_MAPS_HISTORY_URL,
                params={"zone": zone},
                headers={"auth-token": API_KEY},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            history = resp.json().get("history", [])
            values = [h["carbonIntensity"] for h in history
                      if h.get("carbonIntensity") is not None]
            if len(values) >= 2:
                current, low = values[-1], min(values)
                frac = max(0.0, (current - low) / current) if current else 0.0
                result = (round(frac, 3), "live")
        except Exception:
            pass

    if use_cache:
        _shift_cache[region] = result
    return result


if __name__ == "__main__":
    # Quick manual check across all known regions.
    print(f"API key configured: {bool(API_KEY)}")
    for r in CARBON_INTENSITY_FALLBACK:
        ci = get_carbon_intensity(r)
        flag = "CLEAN" if ci.is_clean else "DIRTY" if ci.is_dirty else "mid"
        print(f"  {r:16} -> {ci.label():42} [{flag}]")
    g_region, g_value = greenest_region()
    print(f"greenest: {g_region} ({g_value:.0f} gCO2/kWh)")
