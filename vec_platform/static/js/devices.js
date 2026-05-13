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
const PRICE_TAX = 0.45;             // Phase O: 2026 sänkning (was 0.428 N F8)
const PRICE_FEED_IN = 0.55;         // Phase O: post-skattereduktion (was 0.40 N F7)
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

// Phase O: effekttariff REMOVED. The Swedish 2026 DSO mandate was
// cancelled 2026-03-13 and the major SE3 utilities have withdrawn
// or paused their roll-outs. The previous EFFEKTTARIFF_* constants
// and effekttariffMonthly() helper are gone; computeBillScenario
// no longer adds a peak-kW component to grid_fee.

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
    // Phase O-fix-1: calibrated to Swedish villa+EV household reality.
    // Schuko 10A nödladdning at 2.3 kW (Elsäkerhetsverket standard,
    // most prevalent setup before dedicated wallbox installation) for
    // 3.5 h = 8.05 kWh/day = 241 kWh/month. Targets ~1450 mil/year of
    // driving at 2 kWh/mil, between Trafikanalys vanlig bilägare and
    // Vattenfall E-mobility national EV average. The previous N-fix-4
    // default (4 h × 3.7 kW = 14.8 kWh/day) overstated by 85 %.
    // Default-start 22:00 puts the block in the cheap night window —
    // the SP experiment measures whether users keep it there or drag
    // it into peak hours. 14 slots starting at slot 88 wraps midnight
    // to slot 5 (01:30); the renderer + drag handler already support
    // wrap from Phase 3.X-fix-18.
    default_start: 88,        // 22:00
    default_duration: 14,     // 3.5 h (slots 88-101 wrapping to 0-5)
    load_kw: 2.3,
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
