"""Platform configuration and constants."""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.parent

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{BASE_DIR / 'vec_platform.db'}"
)

# FastAPI settings
API_PREFIX = "/api"
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

# FastGrid VEC pricing constants (SEK)
#
# Phase N F9: RETAIL_PRICE_BASE is DEPRECATED since K-2 F4 replaced the
# flat retail constant with a per-slot integral against the SE3 summer
# retail curve (_SE3_SUMMER_RETAIL_SEK_PER_KWH in engine/mock.py).
# Kept here only for backward import compatibility; calculate_bill no
# longer reads it. Frontend devices.js mirror also marked deprecated.
RETAIL_PRICE_BASE = 1.5  # DEPRECATED — see note above
# Phase N F9: GRID_FEE_MONTHLY is DEPRECATED — flat 580 SEK over-
# charged apartments ~2x and under-charged large villas ~40% vs
# Swedish reality. Replaced by grid_fee_fixed(area_m2) +
# GRID_FEE_VARIABLE_RATE × monthly_kWh. Setting to ``None`` so any
# stale reader fails loudly (TypeError) rather than silently using
# the wrong number.
GRID_FEE_MONTHLY = None  # DEPRECATED — use grid_fee_fixed() + GRID_FEE_VARIABLE_RATE
# Phase N F8: 2026 SE3 residential energy tax (energiskatt),
# VAT-inclusive effective rate. Previously 0.45 (slightly inflated).
ENERGY_TAX = 0.428  # SEK/kWh

# Phase N F6: structured grid fee (nätavgift) = abonnemang (fixed,
# correlated with main breaker ampere via floor area proxy) +
# rörlig elöverföring (variable per kWh).
GRID_FEE_VARIABLE_RATE = 0.30  # SEK/kWh, SE3 median rörlig rate


def grid_fee_fixed(area_m2):
    """Fixed subscription tier (abonnemangsavgift) in SEK/month.

    Tiers approximate the Swedish main-breaker ampere progression
    (16A → 20A → 25A → 35A+) using floor area as a proxy.

    None or sub-80 m² → 100 SEK (apartment / small villa, 16-20A)
    80-149 m² → 200 SEK (standard villa, 20-25A)
    150-249 m² → 300 SEK (larger villa, 25-35A)
    ≥250 m² → 450 SEK (large villa, >35A)
    """
    if area_m2 is None or area_m2 < 80:
        return 100
    if area_m2 < 150:
        return 200
    if area_m2 < 250:
        return 300
    return 450


# VEC internal prices (SEK/kWh)
VEC_INTERNAL_BUY = 0.85
VEC_INTERNAL_SELL = 1.05
# Phase N F7: SE3 utility purchase median for residential PV export.
# Previously 0.95 (~2x reality, inflated PV-owner export value).
FEED_IN_PRICE = 0.40

# ---- Phase N-2: effekttariff (Swedish 2026 DSO mandate) ----
# All Swedish DSOs must implement effekttariff (peak-kW fee) by
# Dec 31 2026. Ellevio rolled out to ~500k villa customers Jan 2026.
# Values below mirror Ellevio's SE3 villa schedule. Tenants pay the
# building's shared grid connection so this fee does not apply to
# them — only owner-occupied dwellings are billed.
#
# Platform simplification: real billing uses the average of the
# month's three highest 1-hour peaks; the mock uses the day's single
# highest 1-hour peak inside the 06-22 day window, then multiplies
# by the per-kW rate to produce one month's effekttariff. The night
# window (22-06) is exempt — shifting load into the night zeroes
# this component, which is precisely the behavioural signal the SP
# experiment wants to surface.
EFFEKTTARIFF_DAY_SEK_PER_KW = 81.25
EFFEKTTARIFF_NIGHT_SEK_PER_KW = 40.62
EFFEKTTARIFF_DAY_START_HOUR = 6
EFFEKTTARIFF_DAY_END_HOUR = 22

# Phase H: effekttariff applies only to housings with their own
# electricity meter and grid connection. BRF condo apartments and
# rented apartments pay through the building's shared connection,
# so the peak-kW fee is collected at the building level, not the
# household level. Mirrors Ellevio's billing scope for SE3 villa
# customers (the 500k-household Jan 2026 roll-out).
EFFEKTTARIFF_HOUSING = frozenset({"townhouse_owner", "villa_owner", "other"})

# CO2 emission factor (kg/kWh) - Nordic mix
CO2_FACTOR = 0.045

# Time slots (96 per day, 15-min intervals)
SLOTS_PER_DAY = 96
SLOT_MINUTES = 15

# Building types
BUILDING_TYPES = ["apartment", "villa_noder", "villa_pv", "villa_pvbess"]

# Heating types
HEATING_TYPES = ["district", "electric", "heatpump"]

# Survey options
WILLINGNESS_OPTIONS = [
    "very_willing",
    "somewhat",
    "need_more_info",
    "unlikely",
    "not_willing"
]

UNWILLING_REASONS = [
    "inconvenient",
    "comfort",
    "not_enough",
    "hassle",
    "other"
]