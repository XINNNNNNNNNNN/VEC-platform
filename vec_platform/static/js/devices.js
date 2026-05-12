// Device catalog + pricing constants for Step 3 live preview.
//
// `default_start` and `default_duration` below MUST match MockEngine
// defaults in vec_platform/engine/mock.py so Step 3's initial render
// matches Step 2.
//
// Phase 3.7-pre (option A): single-instance catalog. Each device type
// can appear at most once in the user's "My devices" list. Multi-instance
// support (e.g., two EV chargers) is deferred to a later phase that also
// redesigns Step 5's per-instance willingness state.

const SLOTS_PER_DAY = 96;
const SLOT_HOURS = 0.25;  // 15 min
const DAYS_PER_MONTH = 30;

// Pricing constants — mirror vec_platform/config.py (SEK).
// Phase N F9: PRICE_RETAIL deprecated (K-2 F4 replaced it with the
// per-slot SE3 retail curve carried via state.spotPrices). Kept for
// fallback when retailArr is not passed. PRICE_GRID_FEE_MONTHLY
// removed — flat 580 over-charged apartments and under-charged
// villas vs Swedish reality; replaced by gridFeeFixed(areaM2) +
// PRICE_GRID_FEE_VARIABLE_RATE × monthlyKwh (Phase N F6).
const PRICE_RETAIL = 1.5;  // DEPRECATED fallback
const PRICE_TAX = 0.428;            // Phase N F8: 2026 SE3 residential
const PRICE_FEED_IN = 0.40;         // Phase N F7: SE3 utility median
const PRICE_VEC_INTERNAL_SELL = 1.05;

// Phase N F6: structured grid fee (nätavgift).
const PRICE_GRID_FEE_VARIABLE_RATE = 0.30;  // SEK/kWh rörlig elöverföring

// Mirror of vec_platform/config.py grid_fee_fixed(area_m2).
function gridFeeFixed(areaM2) {
  if (areaM2 == null || areaM2 < 80) return 100;
  if (areaM2 < 150) return 200;
  if (areaM2 < 250) return 300;
  return 450;
}

// Phase N-2: effekttariff (Swedish 2026 villa peak-kW fee).
// Mirror of vec_platform/config.py EFFEKTTARIFF_* constants.
const EFFEKTTARIFF_DAY_SEK_PER_KW = 81.25;
const EFFEKTTARIFF_DAY_START_HOUR = 6;
const EFFEKTTARIFF_DAY_END_HOUR = 22;

// Owner-only fee; returns 0 for tenants / unknown.
// netLoad is the 96-slot kW array; the day-window hourly peak is the
// same proxy the backend uses (single-day stand-in for monthly
// top-3-hour average).
function effekttariffMonthly(netLoad, ownershipType) {
  if (ownershipType !== "owner" || !Array.isArray(netLoad)) return 0;
  const slotsPerHour = 4;
  let peakKw = 0;
  for (let h = EFFEKTTARIFF_DAY_START_HOUR; h < EFFEKTTARIFF_DAY_END_HOUR; h++) {
    let s = 0;
    for (let k = 0; k < slotsPerHour; k++) {
      s += Math.max(0, netLoad[h * slotsPerHour + k]);
    }
    const avg = s / slotsPerHour;
    if (avg > peakKw) peakKw = avg;
  }
  return peakKw * EFFEKTTARIFF_DAY_SEK_PER_KW;
}

// Naming convention sticks with snake_case to match the existing
// callers in timeline.js + step5.js (default_start / default_duration /
// load_kw). Spec used camelCase but switching would force changes
// across both modules.
//
// `default_include`             — device is on My-devices list by default
// `default_include_when_has_ev` — device is on the list only if user picked
//                                 has_ev in Step 1 (used for ev_charger)
//
// `base_load` is kept here (not draggable, not addable) so timeline.js's
// existing chart trace code (uses DEVICE_CATALOG.base_load.label/color)
// works without changes. It's filtered out of the My-devices list and
// the Add dropdown.
const DEVICE_CATALOG = {
  base_load: {
    label: "Base load (lighting, fridge, peaks)",
    color: "#6c757d",
    draggable: false,
    load_kw: null,  // varies across slots
  },
  cooking: {
    label: "Stove (cooking)",
    color: "#F4B731",  // yellow
    draggable: true,
    default_start: 72,        // 18:00
    default_duration: 4,      // 1 h
    load_kw: 2.0,
    default_include: true,
  },
  dishwasher: {
    label: "Dishwasher",
    color: "#22C55E",  // green
    draggable: true,
    default_start: 78,        // 19:30
    default_duration: 6,      // 1.5 h
    load_kw: 1.2,
    default_include: true,
  },
  washing_machine: {
    label: "Washing machine",
    color: "#3B82F6",  // blue
    draggable: true,
    default_start: 76,        // 19:00
    default_duration: 8,      // 2 h
    load_kw: 2.0,             // ← Phase 3.7-pre: bumped from 0.5
    default_include: true,
  },
  dryer: {
    label: "Tumble dryer",
    color: "#F97316",  // orange
    draggable: true,
    default_start: 84,        // 21:00
    default_duration: 6,      // 1.5 h
    load_kw: 2.5,
    default_include: false,   // user must Add to enable
  },
  oven_baking: {
    label: "Oven (baking)",
    color: "#DC2626",  // red
    draggable: true,
    default_start: 68,        // 17:00
    default_duration: 4,      // 1 h
    load_kw: 2.5,
    default_include: false,   // user must Add to enable
  },
  ev_charger: {
    label: "EV charger",
    color: "#A855F7",  // purple
    draggable: true,
    default_start: 64,        // 16:00
    default_duration: 32,     // 8 h
    load_kw: 3.7,
    default_include_when_has_ev: true,
  },
};

// v3.X-fix-5a-patch: strip the `#N` instance suffix off a state key so
// it matches a DEVICE_CATALOG entry. Bare names pass through unchanged
// (defensive — shouldn't happen post-fix-5a, but cheap to handle).
//   stripInstanceSuffix('cooking#1') -> 'cooking'
//   stripInstanceSuffix('cooking#2') -> 'cooking'
//   stripInstanceSuffix('base_load') -> 'base_load'
// Phase 4-A: the original Python helper (pages/step2.py::_base_device_name)
// was removed when the mock-baseline Step 2 page was deleted. This JS
// stripper is now the canonical implementation.
function stripInstanceSuffix(name) {
  return name.split("#", 1)[0];
}

// fix-5a-patch: dropdown produces bare names. The engine seeds baseline
// instances at `#1`; this helper lets the iteration code address the
// canonical first instance directly. fix-5b extends this with two
// neighbours below for proper multi-instance support.
function stateKeyForBase(baseName) {
  return baseName + "#1";
}

// v3.X-fix-5b: how many instances of a given base device are currently
// in state.placed. 0..MAX_INSTANCES_PER_BASE.
const MAX_INSTANCES_PER_BASE = 3;

function countInstancesOfBase(baseName, statePlaced) {
  let count = 0;
  for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
    if ((baseName + "#" + n) in statePlaced) count++;
  }
  return count;
}

// v3.X-fix-5b: find the lowest unused #N slot for ``baseName``, scanning
// `#1..#MAX_INSTANCES_PER_BASE`. Returns null when all slots are taken
// (caller should treat as "cap reached"). Lowest-unused (rather than
// next-after-highest) lets a freed slot be reused after × removal — so
// removing #2 and re-adding gives `#2`, not `#4`.
function nextStateKeyForBase(baseName, statePlaced) {
  for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
    const key = baseName + "#" + n;
    if (!(key in statePlaced)) return key;
  }
  return null;
}

// v3.X-fix-5b: produce a user-friendly device label. When only one
// instance exists, just the catalog label ("Stove (cooking)"). When
// multiple, append "#N" so the user can tell them apart. Defensive:
// returns the raw key if base is unknown.
function getDeviceLabel(name, statePlaced) {
  const base = stripInstanceSuffix(name);
  const meta = DEVICE_CATALOG[base];
  if (!meta) return name;
  const total = countInstancesOfBase(base, statePlaced);
  if (total <= 1) return meta.label;
  const n = name.split("#")[1] || "1";
  return `${meta.label} #${n}`;
}

function slotToTimeLabel(slot) {
  const h = Math.floor((slot * 15) / 60);
  const m = (slot * 15) % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// Phase 4-A-fix-3: when a device's run crosses midnight (start +
// duration > SLOTS_PER_DAY), the end-of-window timestamp must wrap
// modulo 96 so the label reads "20:45–04:45" instead of "20:45–28:45".
// This is purely a display-side concern — segment widths in makeBlock
// still use the raw, unwrapped duration so the two-segment render
// (Phase 3.X-fix-18) keeps the geometry right.
function rangeLabel(start, duration) {
  const endSlot = (start + duration) % SLOTS_PER_DAY;
  return `${slotToTimeLabel(start)}–${slotToTimeLabel(endSlot)}`;
}
