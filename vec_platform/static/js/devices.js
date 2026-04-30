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
const PRICE_RETAIL = 1.5;
const PRICE_GRID_FEE_MONTHLY = 580;
const PRICE_TAX = 0.45;
const PRICE_FEED_IN = 0.95;
const PRICE_VEC_INTERNAL_SELL = 1.05;

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

function slotToTimeLabel(slot) {
  const h = Math.floor((slot * 15) / 60);
  const m = (slot * 15) % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function rangeLabel(start, duration) {
  return `${slotToTimeLabel(start)}–${slotToTimeLabel(start + duration)}`;
}
