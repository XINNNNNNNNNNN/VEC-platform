// Device catalog + pricing constants for Step 3 live preview.
//
// `start_slot` and `duration_slots` below MUST match MockEngine defaults
// in vec_platform/engine/mock.py so Step 3's initial render matches Step 2.

const SLOTS_PER_DAY = 96;
const SLOT_HOURS = 0.25;  // 15 min
const DAYS_PER_MONTH = 30;

// Pricing constants — mirror vec_platform/config.py (SEK).
const PRICE_RETAIL = 1.5;
const PRICE_GRID_FEE_MONTHLY = 580;
const PRICE_TAX = 0.45;
const PRICE_FEED_IN = 0.95;
const PRICE_VEC_INTERNAL_SELL = 1.05;

// Per the Step 3 prompt:
//   洗衣机蓝色 · 烘干机橙色 · 洗碗机绿色 · EV紫色 · 热水器红色 · 烹饪黄色
// Base load (fridge / lighting / standby / baseline peaks) is grey and
// cannot be moved — the occupant's underlying rhythm, not a shiftable appliance.
const DEVICE_CATALOG = {
  base_load: {
    label: "Base load",
    color: "#6c757d",
    draggable: false,
    load_kw: null, // varies across slots
  },
  cooking_am: {
    label: "Cooking — morning",
    color: "#f1c40f",
    draggable: true,
    default_start: 28, // 07:00
    default_duration: 2, // 30 min
    load_kw: 2.0,
  },
  cooking_pm: {
    label: "Cooking — evening",
    color: "#f39c12",
    draggable: true,
    default_start: 72, // 18:00
    default_duration: 4, // 1 h
    load_kw: 2.0,
  },
  dishwasher: {
    label: "Dishwasher",
    color: "#2ecc71",
    draggable: true,
    default_start: 78, // 19:30
    default_duration: 6, // 1.5 h
    load_kw: 1.2,
  },
  washing_machine: {
    label: "Washing machine",
    color: "#3498db",
    draggable: true,
    default_start: 76, // 19:00
    default_duration: 8, // 2 h
    load_kw: 0.5,
  },
  water_heater: {
    label: "Water heater",
    color: "#e74c3c",
    draggable: true,
    default_start: 20, // 05:00
    default_duration: 8, // 2 h
    load_kw: 3.0,
  },
  ev_charger: {
    label: "EV charger",
    color: "#9b59b6",
    draggable: true,
    default_start: 64, // 16:00
    default_duration: 32, // 8 h
    load_kw: 3.7,
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
