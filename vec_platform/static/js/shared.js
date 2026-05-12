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
  //
  // Phase 4-A-fix-2: wrap-aware. A device whose configured run crosses
  // midnight (e.g. cooking 22:00-02:00) leaves a non-zero block at
  // both ends of the array and a zero gap in the middle. The previous
  // implementation walked left→right tracking first and last non-zero
  // index, returning {start: 0, duration: 96} for such inputs — which
  // downstream rendered as a full-width single block instead of the
  // expected two-segment view, both on /step3 strong-refresh restore
  // and the entire /step5 timeline.
  //
  // The fix: when both the first and last slot are non-zero we are
  // looking at a wrap. Find the largest zero-gap; the slot just after
  // the gap is the run's start, and duration = N − gap_length. Normal
  // (no-wrap), all-zero, full-24h, and single-slot inputs each take a
  // dedicated branch to keep the geometry obvious.
  function extractBounds(arr) {
    if (!Array.isArray(arr) || arr.length === 0) return null;
    const N = arr.length;

    let nonZeroCount = 0;
    for (let i = 0; i < N; i++) if (arr[i] > 0) nonZeroCount++;
    if (nonZeroCount === 0) return null;
    if (nonZeroCount === N) return { start: 0, duration: N };

    const wraps = arr[0] > 0 && arr[N - 1] > 0;

    if (!wraps) {
      // Single contiguous run somewhere in the middle.
      let first = -1, last = -1;
      for (let i = 0; i < N; i++) {
        if (arr[i] > 0) {
          if (first === -1) first = i;
          last = i;
        }
      }
      return { start: first, duration: last - first + 1 };
    }

    // Wrap: scan for the longest zero-gap. Because both endpoints are
    // non-zero, the gap is bounded by non-zero slots on both sides
    // (i.e. it never runs to either end), so a single left-to-right
    // pass captures it correctly.
    let bestGapEnd = -1;
    let bestGapLen = 0;
    let curGapStart = -1;
    for (let i = 0; i < N; i++) {
      if (arr[i] === 0) {
        if (curGapStart === -1) curGapStart = i;
      } else if (curGapStart !== -1) {
        const len = i - curGapStart;
        if (len > bestGapLen) {
          bestGapLen = len;
          bestGapEnd = i;  // first non-zero after the gap
        }
        curGapStart = -1;
      }
    }

    if (bestGapEnd === -1) {
      // Defensive: should be unreachable given wraps && nonZeroCount<N.
      return { start: 0, duration: N };
    }
    return { start: bestGapEnd, duration: N - bestGapLen };
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
  //
  // Phase K-2 F4: ``retailArr`` is the 96-slot per-slot retail price
  // curve. When provided, energy_purchase integrates net_load against
  // the curve so dragging devices to cheap hours produces a real
  // bill reduction. When omitted (legacy callers), falls back to flat
  // PRICE_RETAIL so the function stays usable in contexts that don't
  // load /api/shadow-prices.
  // Phase N F6: ``areaM2`` drives the tiered abonnemang (fixed
  // portion of the grid fee). Default null falls back to the lowest
  // tier (100 SEK) — callers should pass profile.area_m2 from
  // /api/profile so the live preview matches the backend.
  // Phase N-2: ``ownershipType`` ('owner' | 'tenant' | null) gates
  // the Sweden-2026 villa effekttariff (peak-kW fee). Pass
  // profile.ownership_type from /api/profile.
  function computeBillScenario(
    netLoad, scenario, retailArr = null, areaM2 = null, ownershipType = null,
  ) {
    let consumedDaily = 0, exportedDaily = 0;
    let purchaseDaily = 0;
    for (let i = 0; i < netLoad.length; i++) {
      const x = netLoad[i];
      if (x > 0) {
        const kwh = x * SLOT_HOURS;
        consumedDaily += kwh;
        const retail = (retailArr && retailArr.length === netLoad.length)
          ? retailArr[i]
          : PRICE_RETAIL;
        purchaseDaily += kwh * retail;
      } else {
        exportedDaily += -x * SLOT_HOURS;
      }
    }
    const consumedMonthly = consumedDaily * DAYS_PER_MONTH;
    const exportedMonthly = exportedDaily * DAYS_PER_MONTH;

    const energyPurchase = purchaseDaily * DAYS_PER_MONTH;
    // Phase N F6: nätavgift = abonnemang (tier by area) + rörlig
    // elöverföring (× monthly kWh transmitted).
    // Phase N-2: villa owners also pay effekttariff (peak-kW fee).
    // Effekttariff is added to gridFee so the line item displayed on
    // the bill card stays single-row "Grid fee" (no UI shape change).
    const gridFee = gridFeeFixed(areaM2)
      + consumedMonthly * PRICE_GRID_FEE_VARIABLE_RATE
      + effekttariffMonthly(netLoad, ownershipType);
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
