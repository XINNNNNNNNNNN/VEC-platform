// Shared compute helpers used by Step 3 (timeline.js) and Step 5 (step5.js).
// Pure functions — no DOM, no network. All pricing constants live in devices.js.
//
// Globals: VECCompute (compute), VECBessUI (DOM helper for BESS placeholder
// row, kept here so Step 3 and Step 5 produce identical markup).
const VECCompute = (() => {
  // Phase 3.X-fix-18: timeline interpreted as a single 24h cycle, so a
  // device dragged past midnight wraps to the start of the day rather
  // than clamping at the right edge. start is normalised to [0, 96).
  function wrapStart(start, _duration) {
    let s = start % SLOTS_PER_DAY;
    if (s < 0) s += SLOTS_PER_DAY;
    return s;
  }

  // Back-compat alias. Pre-fix-18 callers used clampStart for the same
  // role; now it wraps. Kept as alias so existing call sites stay valid
  // even if not yet updated.
  const clampStart = wrapStart;

  // Detect the start/duration of the single non-zero run inside a 96-slot
  // array. Returns null if the array is all-zero.
  function extractBounds(arr) {
    let start = -1, end = -1;
    for (let i = 0; i < arr.length; i++) {
      if (arr[i] > 0) {
        if (start === -1) start = i;
        end = i + 1;
      }
    }
    if (start === -1) return null;
    return { start, duration: end - start };
  }

  // `placed` is { name: { start, duration, load_kw } }.
  // Returns { name: [96 floats] }.
  // Phase 3.X-fix-18: wrap-aware. A device with start=90, duration=20
  // fills slots 90..95 + 0..13 (wraps midnight), so the live bill
  // matches what the user sees on the wrapped timeline.
  function buildDeviceArrays(placed) {
    const out = {};
    for (const [name, pos] of Object.entries(placed)) {
      const arr = new Array(SLOTS_PER_DAY).fill(0);
      const start = ((pos.start % SLOTS_PER_DAY) + SLOTS_PER_DAY) % SLOTS_PER_DAY;
      const duration = Math.max(0, Math.min(SLOTS_PER_DAY, pos.duration));
      for (let i = 0; i < duration; i++) {
        arr[(start + i) % SLOTS_PER_DAY] = pos.load_kw;
      }
      out[name] = arr;
    }
    return out;
  }

  function computeNetLoad(baseLoad, deviceArrays, pvGeneration) {
    const net = new Array(SLOTS_PER_DAY);
    for (let i = 0; i < SLOTS_PER_DAY; i++) {
      let flex = 0;
      for (const name in deviceArrays) flex += deviceArrays[name][i];
      net[i] = baseLoad[i] + flex - pvGeneration[i];
    }
    return net;
  }

  // Mirrors vec_platform/engine/mock.py MockEngine.calculate_bill so the JS
  // live preview matches the server-side persisted bill.
  function computeBillScenario(netLoad, scenario) {
    let consumedDaily = 0, exportedDaily = 0;
    for (const x of netLoad) {
      if (x > 0) consumedDaily += x * SLOT_HOURS;
      else exportedDaily += -x * SLOT_HOURS;
    }
    const consumedMonthly = consumedDaily * DAYS_PER_MONTH;
    const exportedMonthly = exportedDaily * DAYS_PER_MONTH;

    const energyPurchase = consumedMonthly * PRICE_RETAIL;
    const gridFee = PRICE_GRID_FEE_MONTHLY;
    const tax = consumedMonthly * PRICE_TAX;

    let vecDiscount, feedIn;
    if (scenario === "no_vec") {
      vecDiscount = 0;
      feedIn = exportedMonthly * PRICE_FEED_IN;
    } else if (scenario === "vec_no_adjust") {
      vecDiscount = consumedMonthly * 0.15;
      feedIn = exportedMonthly * PRICE_VEC_INTERNAL_SELL;
    } else {  // vec_adjusted
      vecDiscount = consumedMonthly * 0.25;
      feedIn = exportedMonthly * PRICE_VEC_INTERNAL_SELL;
    }

    const netCost = energyPurchase + gridFee + tax - vecDiscount - feedIn;
    return {
      energy_purchase: energyPurchase,
      grid_fee: gridFee,
      energy_tax: tax,
      vec_discount: vecDiscount,
      feed_in_income: feedIn,
      net_cost: netCost,
    };
  }

  // Find the cheapest window of length `duration` slots in `prices`, for a
  // device drawing `load_kw`. Returns the best start slot and its daily cost.
  // `costAt(start)` lets callers compute current cost with the same formula.
  function cheapestWindow(prices, duration, load_kw) {
    if (duration <= 0 || duration > prices.length) {
      return { bestStart: 0, bestCost: 0 };
    }
    // Sliding-window sum of prices over `duration` slots.
    let windowSum = 0;
    for (let i = 0; i < duration; i++) windowSum += prices[i];
    let bestStart = 0, bestSum = windowSum;
    for (let s = 1; s + duration <= prices.length; s++) {
      windowSum += prices[s + duration - 1] - prices[s - 1];
      if (windowSum < bestSum) {
        bestSum = windowSum;
        bestStart = s;
      }
    }
    return { bestStart, bestCost: bestSum * SLOT_HOURS * load_kw };
  }

  // Cost of running `duration` slots starting at `start` at given prices.
  function costAt(prices, start, duration, load_kw) {
    let s = 0;
    const end = Math.min(prices.length, start + duration);
    for (let i = start; i < end; i++) s += prices[i];
    return s * SLOT_HOURS * load_kw;
  }

  // Phase 3.X-fix-19: BESS placeholder schedule. Find the contiguous
  // window of `n` slots with the smallest sum (charge) and the largest
  // sum (discharge) over `prices`. O(N) sliding window. Returns slot
  // indices in [0, prices.length - n]. Display-only — no bill impact.
  // Caller should pass n=16 for the 4-hour-window assumption (4C cell).
  function findMinSumWindow(prices, n) {
    if (n <= 0 || n > prices.length) return 0;
    let windowSum = 0;
    for (let i = 0; i < n; i++) windowSum += prices[i];
    let bestStart = 0, bestSum = windowSum;
    for (let i = n; i < prices.length; i++) {
      windowSum += prices[i] - prices[i - n];
      if (windowSum < bestSum) { bestSum = windowSum; bestStart = i - n + 1; }
    }
    return bestStart;
  }

  function findMaxSumWindow(prices, n) {
    if (n <= 0 || n > prices.length) return 0;
    let windowSum = 0;
    for (let i = 0; i < n; i++) windowSum += prices[i];
    let bestStart = 0, bestSum = windowSum;
    for (let i = n; i < prices.length; i++) {
      windowSum += prices[i] - prices[i - n];
      if (windowSum > bestSum) { bestSum = windowSum; bestStart = i - n + 1; }
    }
    return bestStart;
  }

  // BESS placeholder schedule used by Step 3 + Step 5. Returns charge
  // start, discharge start, and the shared window length. Schedule is a
  // pure function of `prices` so Step 3 and Step 5 produce identical
  // visuals from the same retail-price array.
  function bessSchedule(prices, windowSlots = 16) {
    const chargeStart = findMinSumWindow(prices, windowSlots);
    const dischargeStart = findMaxSumWindow(prices, windowSlots);
    return { chargeStart, dischargeStart, windowSlots };
  }

  return {
    clampStart,
    wrapStart,
    extractBounds,
    buildDeviceArrays,
    computeNetLoad,
    computeBillScenario,
    cheapestWindow,
    costAt,
    findMinSumWindow,
    findMaxSumWindow,
    bessSchedule,
  };
})();

// Phase 3.X-fix-19: BESS placeholder row builder. Pulled out of
// timeline.js so Step 3 (timeline.js) and Step 5 (step5.js) produce
// identical markup from the same retail-price array. Touches DOM —
// kept here rather than VECCompute (which is pure-compute) to avoid
// duplicating ~30 lines of identical row-building across two files.
const VECBessUI = (() => {
  const BESS_WINDOW_SLOTS = 16;  // 4 hours @ 15-min slots; 4C cell

  // `spotPrices` is expected to be a 96-element retail-price array.
  // Falls back to all-idle if the array is missing or wrong length so
  // the row still renders during transient loading states.
  function makeRow(spotPrices) {
    const row = document.createElement("div");
    row.className = "timeline-row bess-track";

    const label = document.createElement("div");
    label.className = "timeline-row-label";
    label.innerHTML =
      "Battery storage (auto-managed) " +
      "<span class=\"bess-legend\">" +
      "<span class=\"bess-legend-dot bess-charging\"></span> charging " +
      "<span class=\"bess-legend-dot bess-discharging\"></span> discharging" +
      "</span>";
    row.appendChild(label);

    const slots = document.createElement("div");
    slots.className = "bess-slots";

    let schedule = null;
    if (Array.isArray(spotPrices) && spotPrices.length === SLOTS_PER_DAY) {
      schedule = VECCompute.bessSchedule(spotPrices, BESS_WINDOW_SLOTS);
    }

    for (let i = 0; i < SLOTS_PER_DAY; i++) {
      const slot = document.createElement("div");
      slot.className = "bess-slot";
      if (schedule) {
        const inCharge = i >= schedule.chargeStart
          && i < schedule.chargeStart + schedule.windowSlots;
        const inDischarge = i >= schedule.dischargeStart
          && i < schedule.dischargeStart + schedule.windowSlots;
        if (inCharge) slot.classList.add("bess-charging");
        else if (inDischarge) slot.classList.add("bess-discharging");
        else slot.classList.add("bess-idle");
      } else {
        slot.classList.add("bess-idle");
      }
      slots.appendChild(slot);
    }
    row.appendChild(slots);
    return row;
  }

  return { makeRow, BESS_WINDOW_SLOTS };
})();
