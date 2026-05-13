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
# Phase O: Sweden 2026-01-01 sänkning of residential energy tax
# (energiskatt). Government cut the rate by 9.875 öre from 54.875
# to 45.0 öre/kWh (incl 25% VAT). Replaces the Phase N F8 estimate
# of 0.428 which was based on pre-cut data.
ENERGY_TAX = 0.45  # SEK/kWh incl VAT

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
# Phase O: post-skattereduktion feed-in price. The 60-öre tax credit
# (skattereduktion) for residential PV export was repealed 2026-01-01,
# so the household-facing feed-in rate is now spot price + small
# utility margin only. Typical 2026 H1: spot ~0.50 + 5 öre påslag +
# 5 öre nätnytta ≈ 0.55 SEK/kWh. Previously 0.40 (Phase N F7) was a
# conservative mid-2025 figure that under-estimated post-cut value.
FEED_IN_PRICE = 0.55  # SEK/kWh

# ---- Phase O-fix-3: EV daily charging (user-configurable) ----
# Phase O-fix-1 fixed daily charge at 8.05 kWh (Swedish villa+EV avg)
# to align mock with reality. Phase O-fix-3 lets the participant override
# the default in the Step 3 calibration panel so different commute
# profiles can be modelled. The field name on user_inputs.ev_kwh is
# REPURPOSED — it used to mean vehicle battery capacity (e.g. 60 kWh
# Tesla Model 3) but daily charging is driven by commute distance,
# not battery size. New semantics: daily charging energy in kWh.
#
# Power stays at 2.3 kW (Schuko 10A) so the block duration scales:
#   ev_kwh =  2 kWh -> ~0.9 h (~3 slots) — light city commute
#   ev_kwh =  8 kWh -> ~3.5 h (~14 slots) — DEFAULT, ~40 km commute
#   ev_kwh = 12 kWh -> ~5.2 h (~21 slots) — heavy commute
#   ev_kwh = 24 kWh -> ~10.4 h (~42 slots) — upper bound
# Anything beyond ~24 kWh starts overlapping daytime hours and
# departs from the typical-day mock; the calibration panel caps
# the input at EV_MAX_DAILY_KWH.
EV_DEFAULT_DAILY_KWH = 8.05
EV_MIN_DAILY_KWH = 2.0
EV_MAX_DAILY_KWH = 24.0
EV_POWER_KW = 2.3
EV_DEFAULT_START_SLOT = 88   # 22:00 — overnight charging window

# ---- Phase O-fix-2: BESS daily dispatch ----
# Two user-draggable windows (charge + discharge), each 4 hours
# (16 quarter-slots). Round-trip efficiency 0.9 (IEC 62933 industry
# standard) — daily cycle 10 kWh charge produces 9 kWh discharge.
#
# Visually both windows are drawn at 2.5 kW (consistent block height
# in the timeline); the actual energy balance is computed from
# CHARGE_KWH_PER_DAY / DISCHARGE_KWH_PER_DAY inside the dispatch
# logic, where the round-trip loss is bookkept. bess_kwh capacity
# from Step 1 / Step 3 calibration does NOT affect the daily cycle
# in this phase; it is retained as an informational user input.
# Future Phase K-3 may add user-controlled cycle depth scaling
# with bess_kwh.
# Phase O-fix-5: BESS daily cycle size is user-configurable, parallel
# to EV. Power stays fixed at 2.5 kW (Schuko-equivalent) so the
# duration scales with bess_kwh:
#   bess_kwh =  2 -> 0.8 h (~3 slots) — small lithium booster
#   bess_kwh =  5 -> 2.0 h (~8 slots)
#   bess_kwh = 10 -> 4.0 h (~16 slots) — DEFAULT (Powerwall-class)
#   bess_kwh = 20 -> 8.0 h (~32 slots) — upper bound
# Cap at 20 kWh so charge + discharge windows never exceed ~16 h /
# day and there is always room to wrap-shift without colliding.
# Daily cycle FIXED 1/day (the "cycle 死的" design constraint);
# what is now dynamic is the cycle SIZE.
BESS_DEFAULT_KWH = 10.0
BESS_MIN_KWH = 2.0
BESS_MAX_KWH = 20.0
BESS_POWER_KW = 2.5
BESS_EFFICIENCY = 0.9

# Default schedule slots (user can drag in Step 3 timeline).
# Charge default: PV-surplus midday window (slot 44 = 11:00).
# Discharge default: evening retail peak (slot 72 = 18:00).
BESS_CHARGE_DEFAULT_START = 44
BESS_DISCHARGE_DEFAULT_START = 72

# ---- Phase N-2 effekttariff REMOVED in Phase O ----
# The Swedish 2026 DSO effekttariff mandate was cancelled on
# 2026-03-13. Ellevio reverted 2026-06-01, Mälarenergi 2026-07-01,
# Göteborg Energi stopped, and E.ON's winter-only model
# (effective 2026-09-01) has not yet published an exact formula.
# Most pilot users (running 2026 H2) will see no effekttariff line
# on their real bills, so the mock no longer adds it. The paper's
# method section documents this policy reversal.

# CO2 emission factor (kg/kWh) - Nordic mix
CO2_FACTOR = 0.045

# Time slots (96 per day, 15-min intervals)
SLOTS_PER_DAY = 96
SLOT_MINUTES = 15

# Phase O: building_type 4-way classification aligned with the
# E.ON Sweden consumer survey 2025. Effekttariff was removed in
# this phase, so there is no longer an ownership-driven split —
# the engine only needs to know whether the dwelling is an
# apartment (district heating, smaller appliance kit) or a house
# (heat pump, larger appliance kit). townhouse / house / other all
# share the house archetype calibration (Phase N-fix-4).
BUILDING_TYPE_VALUES = ("apartment", "townhouse", "house", "other")
APARTMENT_BUILDINGS = frozenset({"apartment"})
HOUSE_BUILDINGS = frozenset({"townhouse", "house", "other"})

# Legacy v2 list still referenced by historical migrations / analyst
# tooling. Phase O does not write to these codes; kept for grep-able
# rollback safety.
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