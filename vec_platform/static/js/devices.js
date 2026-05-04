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

// v3.X-fix-5a-patch: strip the `#N` instance suffix off a state key so
// it matches a DEVICE_CATALOG entry. Bare names pass through unchanged
// (defensive — shouldn't happen post-fix-5a, but cheap to handle).
//   stripInstanceSuffix('cooking#1') -> 'cooking'
//   stripInstanceSuffix('cooking#2') -> 'cooking'
//   stripInstanceSuffix('base_load') -> 'base_load'
// Mirrors pages/step2.py::_base_device_name on the backend so both ends
// strip suffixes the same way.
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

function rangeLabel(start, duration) {
  return `${slotToTimeLabel(start)}–${slotToTimeLabel(start + duration)}`;
}
