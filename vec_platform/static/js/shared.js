// Shared compute helpers used by Step 3 (timeline.js) and Step 5 (step5.js).
// Pure functions — no DOM, no network. All pricing constants live in devices.js.
//
// Global: VECCompute
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

  return {
    clampStart,
    wrapStart,
    extractBounds,
    buildDeviceArrays,
    computeNetLoad,
    computeBillScenario,
    cheapestWindow,
    costAt,
  };
})();
