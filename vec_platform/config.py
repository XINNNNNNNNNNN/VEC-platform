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
RETAIL_PRICE_BASE = 1.5  # SEK/kWh
GRID_FEE_MONTHLY = 580  # SEK/month
ENERGY_TAX = 0.45  # SEK/kWh

# VEC internal prices (SEK/kWh)
VEC_INTERNAL_BUY = 0.85
VEC_INTERNAL_SELL = 1.05
FEED_IN_PRICE = 0.95

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