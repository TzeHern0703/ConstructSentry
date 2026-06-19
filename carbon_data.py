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

try:  # requests is optional — fallback works without any network stack
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore


# --- Configuration ---------------------------------------------------------

ELECTRICITY_MAPS_URL = "https://api.electricitymap.org/v3/carbon-intensity/latest"

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


if __name__ == "__main__":
    # Quick manual check across all known regions.
    print(f"API key configured: {bool(API_KEY)}")
    for r in CARBON_INTENSITY_FALLBACK:
        ci = get_carbon_intensity(r)
        flag = "CLEAN" if ci.is_clean else "DIRTY" if ci.is_dirty else "mid"
        print(f"  {r:16} -> {ci.label():42} [{flag}]")
    g_region, g_value = greenest_region()
    print(f"greenest: {g_region} ({g_value:.0f} gCO2/kWh)")
