// Step 5 UI: respond to tomorrow's shadow prices.
//
// Differences from Step 3:
//   - Devices start from the Step 3 customized schedule, not Step 2 defaults.
//   - Each device shows a "move to XX:XX–YY:YY to save Z SEK/day" suggestion
//     based on the community's internal-buy price curve.
//   - Each device has willing / not-willing controls + a reason multi-select.
//   - The chart overlays three net-load lines (Step 2 grey, Step 3 blue,
//     live Step 5 green) so users can see their impact.
//   - Confirm persists device_shifts with willing + unwilling_reason, then
//     recalculates at step=5.

(() => {
  const STEP = 5;

  const UNWILLING_REASONS = [
    { value: "inconvenient", label: "Time inconvenient" },
    { value: "comfort",      label: "Affects comfort" },
    { value: "not_enough",   label: "Savings not enough" },
    { value: "hassle",       label: "Too much hassle" },
    { value: "other",        label: "Other" },
  ];

  // Suggestion threshold — don't bother users with trivial savings.
  const SAVINGS_THRESHOLD_SEK_DAY = 0.5;

  const state = {
    sessionId: null,
    baseLoad: null,
    pvGeneration: null,
    shadowPrices: null,        // { retail_price, internal_buy, internal_sell, feed_in_price }
    // Phase 3.X-fix-19: drives the BESS placeholder track on Step 5
    // (mirrors timeline.js fix-18+19). Schedule comes from shadowPrices,
    // so the visual matches Step 3's BESS row exactly.
    hasBess: false,
    step2NetLoad: null,
    step3NetLoad: null,
    originalPositions: {},     // Step 3 positions, the starting point
    // v3.X-fix-2: most recent position the user actively dragged a device to.
    // Empty if user never moved that device. Used by setWillingness to
    // restore the user's adjusted position when willing flips back to true,
    // and by Confirm to write the right position to device_shifts.
    shiftedPositions: {},
    placed: {},                // Live positions in Step 5
    willingness: {},           // { name: { willing: bool, reasons: Set<string> } }
    bills: {
      noVec: null,             // Step 3 no_vec baseline (for "without VEC" column)
      vecNoAdjust: null,       // Step 3 vec_no_adjust (for "VEC, same schedule")
    },
    // Phase N F6: floor area for tiered grid fee in live recompute.
    areaM2: null,
    // Phase H+1: building shape + ownership flag gating the
    // effekttariff in the live recompute (Step 5 willingness toggle
    // bill preview).
    buildingType: null,
    isOwner: null,
    // Phase H (DEPRECATED): legacy 5-way housing_type fallback.
    housingType: null,
    // Pre-Phase-H legacy: ownership_type 2-way fallback.
    ownershipType: null,
  };

  function $(id) { return document.getElementById(id); }

  function showError(msg) {
    const el = $("error-banner");
    el.textContent = msg;
    el.classList.remove("d-none");
  }

  // ---- Timeline rendering ----
  function renderAxis() {
    const axis = document.createElement("div");
    axis.className = "timeline-axis";
    for (let h = 0; h <= 24; h += 3) {
      const tick = document.createElement("div");
      tick.className = "timeline-tick";
      tick.style.left = `${(h / 24) * 100}%`;
      tick.textContent = `${String(h).padStart(2, "0")}:00`;
      axis.appendChild(tick);
    }
    return axis;
  }

  // Phase 3.7-pre: device list collapsed (cooking_am+cooking_pm -> cooking,
  // water_heater dropped) and dryer/oven_baking added. Order matches
  // DEVICE_CATALOG declaration so the rendered timeline / cards mirror
  // Step 3's "My devices" list.
  const DEVICE_ROW_ORDER = [
    "cooking", "dishwasher", "washing_machine",
    "dryer", "oven_baking", "ev_charger",
  ];

  function renderTimeline() {
    const container = $("timeline");
    container.innerHTML = "";
    container.appendChild(renderAxis());

    // Rigid base-load row (non-draggable).
    const rigidRow = document.createElement("div");
    rigidRow.className = "timeline-row rigid";
    const rigidLabel = document.createElement("div");
    rigidLabel.className = "timeline-row-label";
    rigidLabel.textContent = "Base load (fridge / lighting / peaks)";
    rigidRow.appendChild(rigidLabel);
    container.appendChild(rigidRow);

    // Phase 3.X-fix-19: BESS placeholder row, identical schedule to
    // Step 3 (both compute from the same retail-price array via the
    // shared VECBessUI.makeRow helper).
    if (state.hasBess) {
      const prices = state.shadowPrices && state.shadowPrices.retail_price;
      container.appendChild(VECBessUI.makeRow(prices));
    }

    // v3.X-fix-5b: expand each base type to its #1..MAX_INSTANCES_PER_BASE
    // instances so users see one timeline row per instance. Row label
    // uses getDeviceLabel so multi-instance shows "Stove (cooking) #2".
    for (const baseName of DEVICE_ROW_ORDER) {
      for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
        const name = `${baseName}#${n}`;
        if (!(name in state.placed)) continue;
        const row = document.createElement("div");
        row.className = "timeline-row";

        const rowLabel = document.createElement("div");
        rowLabel.className = "timeline-row-label";
        rowLabel.textContent = getDeviceLabel(name, state.placed);
        row.appendChild(rowLabel);

        // Phase 3.X-fix-18: makeBlock now returns one segment for normal
        // devices and two for those whose run wraps midnight (mirrors
        // timeline.js).
        for (const block of makeBlock(name)) {
          row.appendChild(block);
        }
        container.appendChild(row);
      }
    }
  }

  // Phase 3.X-fix-18: returns [tail, head] when the configured run
  // crosses midnight, otherwise [singleBlock]. Both segments share the
  // same `name` and drag handler keyed on `name`.
  function makeBlock(name) {
    const meta = DEVICE_CATALOG[stripInstanceSuffix(name)];
    const pos = state.placed[name];
    const start = pos.start;
    const duration = pos.duration;
    const wraps = (start + duration) > SLOTS_PER_DAY;

    if (!wraps) {
      return [_makeSegment(name, meta, start, duration, /*segRole=*/null)];
    }
    const tailDur = SLOTS_PER_DAY - start;
    const headDur = duration - tailDur;
    return [
      _makeSegment(name, meta, start, tailDur, "tail"),
      _makeSegment(name, meta, 0, headDur, "head"),
    ];
  }

  function _makeSegment(name, meta, segStart, segDuration, segRole) {
    const block = document.createElement("div");
    block.className = "device-block";
    if (segRole) block.classList.add(`device-block-${segRole}`);
    block.dataset.device = name;
    block.style.background = meta.color;
    block.style.left = `${(segStart / SLOTS_PER_DAY) * 100}%`;
    block.style.width = `${(segDuration / SLOTS_PER_DAY) * 100}%`;

    const labelSpan = document.createElement("span");
    labelSpan.className = "device-block-label";
    block.appendChild(labelSpan);
    updateBlockLabel(block, name);

    if (meta.draggable) attachDrag(block, name);
    return block;
  }

  function updateBlockLabel(block, name) {
    const pos = state.placed[name];
    // v3.X-fix-5b: friendly label so multi-instance blocks are
    // distinguishable on hover.
    const friendly = getDeviceLabel(name, state.placed);
    block.title = `${friendly} · ${pos.load_kw} kW · ${rangeLabel(pos.start, pos.duration)}`;
    const label = block.querySelector(".device-block-label");
    if (label) label.textContent = rangeLabel(pos.start, pos.duration);
  }

  // ---- Drag ----
  function attachDrag(block, name) {
    let startX = 0;
    let startSlotAtPointerDown = 0;
    let rowWidth = 0;
    let preDragStart = 0;
    let preDragEnd = 0;

    block.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const row = block.parentElement;
      rowWidth = row.getBoundingClientRect().width;
      startX = e.clientX;
      startSlotAtPointerDown = state.placed[name].start;
      preDragStart = state.placed[name].start;
      preDragEnd = preDragStart + state.placed[name].duration;
      block.setPointerCapture(e.pointerId);
      block.classList.add("dragging");
    });

    block.addEventListener("pointermove", (e) => {
      if (!block.classList.contains("dragging")) return;
      const dx = e.clientX - startX;
      const dSlots = Math.round((dx / rowWidth) * SLOTS_PER_DAY);
      // Phase 3.X-fix-18: wrap (modulo) instead of clamp so dragging a
      // device past midnight lands it on the other side of the day.
      const newStart = VECCompute.wrapStart(startSlotAtPointerDown + dSlots);
      if (newStart !== state.placed[name].start) {
        state.placed[name].start = newStart;
        // Phase 4-A-fix-4: real-time wrap rendering (mirrors
        // timeline.js — keep both pages visually identical during
        // drag). Resize the held block to its tail and show a
        // transient head companion while the user is crossing
        // midnight; remove the companion when the drag returns
        // to non-wrap. renderTimeline() on pointerup replaces the
        // transient companion with makeBlock's permanent two-
        // segment output.
        const duration = state.placed[name].duration;
        const wraps = (newStart + duration) > SLOTS_PER_DAY;
        const row = block.parentElement;
        let companion = row.querySelector(
          `[data-drag-companion="${name}"]`
        );
        if (wraps) {
          const tailDur = SLOTS_PER_DAY - newStart;
          const headDur = duration - tailDur;
          block.style.left = `${(newStart / SLOTS_PER_DAY) * 100}%`;
          block.style.width = `${(tailDur / SLOTS_PER_DAY) * 100}%`;
          if (!companion) {
            companion = document.createElement("div");
            companion.className = "device-block device-block-head";
            companion.dataset.dragCompanion = name;
            companion.style.background = block.style.background;
            row.appendChild(companion);
          }
          companion.style.left = "0%";
          companion.style.width = `${(headDur / SLOTS_PER_DAY) * 100}%`;
        } else {
          block.style.left = `${(newStart / SLOTS_PER_DAY) * 100}%`;
          block.style.width = `${(duration / SLOTS_PER_DAY) * 100}%`;
          if (companion) companion.remove();
        }
        updateBlockLabel(block, name);
        refreshChart();
        updateDeviceCard(name);   // live-update suggestion chip & range
      }
    });

    function endDrag(e) {
      if (!block.classList.contains("dragging")) return;
      block.classList.remove("dragging");
      try { block.releasePointerCapture(e.pointerId); } catch (_) {}
      const newStart = state.placed[name].start;
      const newEnd = newStart + state.placed[name].duration;
      if (newStart !== preDragStart) {
        // v3.X-fix-2: snapshot the user's adjusted position so we can
        // restore it if they toggle willing=no and then willing=yes again.
        // Only record on real drags (not no-op clicks) and not on programmatic
        // moves like setWillingness rollback — those don't go through endDrag.
        state.shiftedPositions[name] = { ...state.placed[name] };

        // v3.X-fix-3: dragging invalidates any prior willing yes/no for
        // this device. The user has just moved the device to a new
        // position, so any earlier statement about willingness is stale —
        // force them to re-decide. Clear state + DOM (radios + reasons
        // checkboxes + reasons block visibility) and re-evaluate the
        // Submit gate (which now requires every device answered).
        // Side-stepping setWillingness on purpose: it has its own position
        // restore path that we don't want to trigger here.
        state.willingness[name].willing = null;
        state.willingness[name].reasons.clear();
        const card = $("device-cards").querySelector(`.device-card[data-device="${name}"]`);
        if (card) {
          card.querySelectorAll(`input[name="willing-${name}"]`).forEach((r) => { r.checked = false; });
          const reasons = card.querySelector("[data-role=reasons]");
          if (reasons) {
            reasons.classList.add("hidden");
            reasons.querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = false; });
          }
        }
        updateConfirmEnabled();

        VECApi.logDrag({
          session_id: state.sessionId,
          step: STEP,
          device_name: name,
          from_start: preDragStart,
          from_end: preDragEnd,
          to_start: newStart,
          to_end: newEnd,
          action: "move",
        }).catch((err) => console.warn("drag-log failed", err));
      }
      // Phase 3.X-fix-18: re-render so a wrapped device shows as two
      // cleanly aligned segments (tail at right, head at left) rather
      // than a single block clipped at the right edge.
      renderTimeline();
    }

    block.addEventListener("pointerup", endDrag);
    block.addEventListener("pointercancel", endDrag);
  }

  // ---- Suggestions ----
  function buildSuggestion(name) {
    const pos = state.placed[name];
    const prices = state.shadowPrices.internal_buy;
    const { bestStart, bestCost } = VECCompute.cheapestWindow(prices, pos.duration, pos.load_kw);
    const currentCost = VECCompute.costAt(prices, pos.start, pos.duration, pos.load_kw);
    const savings = currentCost - bestCost;
    if (bestStart === pos.start || savings < SAVINGS_THRESHOLD_SEK_DAY) {
      return { chipClass: "good", text: "✓ Already in a cheap window." };
    }
    return {
      chipClass: "",
      text: `Move to ${rangeLabel(bestStart, pos.duration)} to save ≈ ${savings.toFixed(1)} SEK/day.`,
    };
  }

  // ---- Device decision cards ----
  function renderDeviceCards() {
    const root = $("device-cards");
    root.innerHTML = "";
    // v3.X-fix-5b: render one card per instance #1..MAX_INSTANCES_PER_BASE
    // so each cooking#N gets its own willing radio + reasons + drag block.
    for (const baseName of DEVICE_ROW_ORDER) {
      for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
        const name = `${baseName}#${n}`;
        if (!(name in state.placed)) continue;
        root.appendChild(makeDeviceCard(name));
      }
    }
  }

  function makeDeviceCard(name) {
    const meta = DEVICE_CATALOG[stripInstanceSuffix(name)];
    const card = document.createElement("div");
    card.className = "device-card";
    card.dataset.device = name;

    const header = document.createElement("div");
    header.className = "device-card-header";

    const title = document.createElement("div");
    title.className = "device-card-title";
    const swatch = document.createElement("span");
    swatch.className = "device-swatch";
    swatch.style.background = meta.color;
    const nameSpan = document.createElement("span");
    // v3.X-fix-5b: show "Stove (cooking) #2" when multiple instances of
    // the same base device exist; just "Stove (cooking)" when only one.
    nameSpan.textContent = getDeviceLabel(name, state.placed);
    const rangeSpan = document.createElement("span");
    rangeSpan.className = "text-muted small ms-2";
    rangeSpan.dataset.role = "range";
    title.appendChild(swatch);
    title.appendChild(nameSpan);
    title.appendChild(rangeSpan);

    const chip = document.createElement("span");
    chip.className = "suggestion-chip";
    chip.dataset.role = "suggestion";

    header.appendChild(title);
    header.appendChild(chip);
    card.appendChild(header);

    const body = document.createElement("div");
    body.className = "device-card-body";
    body.appendChild(makeWillingnessRow(name));
    body.appendChild(makeReasonsRow(name));
    card.appendChild(body);

    updateDeviceCardFromElement(card, name);
    return card;
  }

  function makeWillingnessRow(name) {
    const row = document.createElement("div");
    row.className = "willingness-row";
    const group = `willing-${name}`;

    const willYes = document.createElement("label");
    willYes.className = "form-check-label";
    const willYesInput = document.createElement("input");
    willYesInput.type = "radio";
    willYesInput.className = "form-check-input me-1";
    willYesInput.name = group;
    willYesInput.value = "yes";
    willYesInput.checked = state.willingness[name].willing === true;
    willYesInput.addEventListener("change", () => setWillingness(name, true));
    willYes.appendChild(willYesInput);
    willYes.appendChild(document.createTextNode("I'm willing to adjust"));

    const willNo = document.createElement("label");
    willNo.className = "form-check-label";
    const willNoInput = document.createElement("input");
    willNoInput.type = "radio";
    willNoInput.className = "form-check-input me-1";
    willNoInput.name = group;
    willNoInput.value = "no";
    willNoInput.checked = state.willingness[name].willing === false;
    willNoInput.addEventListener("change", () => setWillingness(name, false));
    willNo.appendChild(willNoInput);
    willNo.appendChild(document.createTextNode("I'm not willing to adjust"));

    row.appendChild(willYes);
    row.appendChild(willNo);
    return row;
  }

  function makeReasonsRow(name) {
    const row = document.createElement("div");
    row.className = "reasons-row hidden";
    row.dataset.role = "reasons";

    const header = document.createElement("div");
    header.className = "w-100 small text-muted";
    header.textContent = "Why not? (select all that apply)";
    row.appendChild(header);

    for (const { value, label } of UNWILLING_REASONS) {
      const wrap = document.createElement("label");
      wrap.className = "form-check-label me-2";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.className = "form-check-input me-1";
      box.value = value;
      box.checked = state.willingness[name].reasons.has(value);
      box.addEventListener("change", () => toggleReason(name, value, box.checked));
      wrap.appendChild(box);
      wrap.appendChild(document.createTextNode(label));
      row.appendChild(wrap);
    }
    return row;
  }

  function setWillingness(name, willing) {
    state.willingness[name].willing = willing;
    if (willing) state.willingness[name].reasons.clear();

    // v3.X-fix-1 + v3.X-fix-2: position memory across willing toggle.
    //   willing=no  → revert to step 3 baseline (originalPositions). Saying
    //                 "I wouldn't shift this for VEC prices" while the chart
    //                 keeps showing a shifted position is a data-semantic
    //                 mismatch.
    //   willing=yes → restore the user's most recent dragged position
    //                 (shiftedPositions). Falls back to baseline when the
    //                 user has never dragged this device, so the call is a
    //                 no-op in that case.
    // shiftedPositions is intentionally NOT updated here — these are
    // programmatic moves driven by the willing toggle, not new user intent.
    if (willing) {
      const target = state.shiftedPositions[name] || state.originalPositions[name];
      if (target) {
        state.placed[name] = { ...target };
        renderTimeline();
        updateDeviceCard(name);
        refreshChart();
      }
    } else if (state.originalPositions[name]) {
      state.placed[name] = { ...state.originalPositions[name] };
      renderTimeline();
      updateDeviceCard(name);
      refreshChart();
    }

    const card = $("device-cards").querySelector(`.device-card[data-device="${name}"]`);
    if (card) {
      const reasons = card.querySelector("[data-role=reasons]");
      if (willing) {
        reasons.classList.add("hidden");
        // Uncheck all boxes visually.
        reasons.querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = false; });
      } else {
        reasons.classList.remove("hidden");
      }
    }

    // v3.X-fix-3: re-evaluate Submit gate. Now that willing is no longer
    // defaulted to true, every yes/no click flips the all-devices-answered
    // condition and may enable/disable Submit.
    updateConfirmEnabled();
  }

  function toggleReason(name, reason, on) {
    const s = state.willingness[name].reasons;
    if (on) s.add(reason); else s.delete(reason);
  }

  function updateDeviceCard(name) {
    const card = $("device-cards").querySelector(`.device-card[data-device="${name}"]`);
    if (card) updateDeviceCardFromElement(card, name);
  }

  function updateDeviceCardFromElement(card, name) {
    const pos = state.placed[name];
    const range = card.querySelector("[data-role=range]");
    if (range) range.textContent = `· ${rangeLabel(pos.start, pos.duration)} · ${pos.load_kw} kW`;
    const chip = card.querySelector("[data-role=suggestion]");
    if (chip) {
      const { chipClass, text } = buildSuggestion(name);
      chip.className = "suggestion-chip " + chipClass;
      chip.textContent = text;
    }
  }

  // ---- Chart + bill ----
  function hours() {
    const out = new Array(SLOTS_PER_DAY);
    for (let i = 0; i < SLOTS_PER_DAY; i++) out[i] = (i * 15) / 60;
    return out;
  }

  function refreshChart() {
    const x = hours();
    const deviceArrays = VECCompute.buildDeviceArrays(state.placed);
    const netNow = VECCompute.computeNetLoad(state.baseLoad, deviceArrays, state.pvGeneration);

    const traces = [
      {
        x, y: state.step2NetLoad,
        name: "Baseline",
        mode: "lines",
        line: { color: "#adb5bd", width: 1.5, dash: "dash" },
        hovertemplate: "%{y:.2f} kW<extra>Baseline</extra>",
      },
      {
        x, y: state.step3NetLoad,
        // Phase 4-A: customize is Step 2 in the new 7-step flow.
        name: "Step 2 — your first pass",
        mode: "lines",
        line: { color: "#3498db", width: 2 },
        hovertemplate: "%{y:.2f} kW<extra>First pass</extra>",
      },
      {
        x, y: netNow,
        // Phase 4-A: respond is Step 4 in the new 7-step flow.
        name: "Step 4 — after responding",
        mode: "lines",
        line: { color: "#27ae60", width: 2.5 },
        hovertemplate: "%{y:.2f} kW<extra>Live</extra>",
      },
    ];

    // Overlay internal-buy price on a secondary axis so users can see the
    // cheap hours while dragging.
    traces.push({
      x, y: state.shadowPrices.internal_buy,
      name: "VEC internal buy (SEK/kWh)",
      mode: "lines",
      yaxis: "y2",
      line: { color: "#e67e22", width: 1, dash: "dot" },
      hovertemplate: "%{y:.2f} SEK/kWh<extra>VEC buy</extra>",
    });

    const layout = {
      margin: { l: 50, r: 50, t: 20, b: 40 },
      xaxis: {
        title: "Hour of day",
        tickmode: "array",
        tickvals: [0, 3, 6, 9, 12, 15, 18, 21, 24],
        range: [0, 24],
      },
      yaxis: { title: "Net load (kW)" },
      yaxis2: {
        title: "Price (SEK/kWh)",
        overlaying: "y",
        side: "right",
        showgrid: false,
      },
      legend: { orientation: "h", yanchor: "bottom", y: -0.35 },
      hovermode: "x unified",
    };

    Plotly.react("compare-chart", traces, layout, { displayModeBar: false });
    refreshBillCompare(netNow);
  }

  function refreshBillCompare(netNow) {
    const el = $("bill-compare");
    // Phase K-2 F4: per-slot retail curve so the green "after responding"
    // bill drops when the user shifts loads into cheap (PV-trough) hours.
    const retailArr = state.shadowPrices && state.shadowPrices.retail_price;
    // Phase N F6: areaM2 for tiered grid_fee, matching backend.
    // Phase H+1: buildingType + isOwner for effekttariff parity;
    // legacy housingType + ownershipType passed as fallbacks.
    const adjusted = VECCompute.computeBillScenario(
      netNow, "vec_adjusted", retailArr, state.areaM2,
      state.buildingType, state.isOwner,
      state.housingType, state.ownershipType
    );

    function col(label, value, extraClass = "") {
      const v = value === null || value === undefined
        ? "—"
        : `${value.toLocaleString("en-US", { maximumFractionDigits: 0 })} SEK`;
      return `
        <div class="bill-compare-col ${extraClass}">
          <div class="bill-compare-label">${label}</div>
          <div class="bill-compare-value">${v}</div>
        </div>
      `;
    }

    const noVec = state.bills.noVec ? state.bills.noVec.net_cost : null;
    const vecSame = state.bills.vecNoAdjust ? state.bills.vecNoAdjust.net_cost : null;
    el.innerHTML =
      col("Without VEC", noVec) +
      col("VEC · same schedule", vecSame) +
      col("VEC · after responding (live)", adjusted.net_cost, "current");
  }

  // ---- Initial load ----
  async function loadInitial() {
    state.sessionId = VECApi.getSessionId();
    if (!state.sessionId) {
      showError("No session_id in the URL. Please start from Step 1.");
      return;
    }
    $("session-label").textContent = `Session: ${state.sessionId.slice(0, 8)}…`;

    let step3, step2, shadow;
    try {
      // Step 3 is the user's customized schedule (the starting point for
      // Step 5). Fall back to step 2 if the user somehow skipped step 3.
      [step2, shadow] = await Promise.all([
        VECApi.getProfile(state.sessionId, 2),
        VECApi.getShadowPrices(state.sessionId),
      ]);
      try {
        step3 = await VECApi.getProfile(state.sessionId, 3);
      } catch (_) {
        step3 = step2;
      }
    } catch (err) {
      console.error(err);
      showError("Could not load your profile. Please complete Step 1–4 first.");
      return;
    }

    state.baseLoad = step2.rigid_load;
    state.pvGeneration = step2.pv_generation;
    state.step2NetLoad = step2.net_load;
    state.step3NetLoad = step3.net_load;
    state.shadowPrices = shadow;
    // Phase N F6: floor area drives the tiered grid fee in the live
    // recompute below (when user toggles willingness, we recompute
    // bill from current net load — must use same fee structure as
    // backend). Falls back to step3 area if step2 missing it.
    state.areaM2 = step2.area_m2 ?? step3.area_m2 ?? null;
    // Phase H+1: building_type + is_owner gate effekttariff in the
    // live recompute. Same fallback chain as areaM2.
    state.buildingType = step2.building_type ?? step3.building_type ?? null;
    state.isOwner = step2.is_owner ?? step3.is_owner ?? null;
    // Phase H legacy: housing_type fallback for sessions whose
    // /api/profile response predates the building_type column.
    state.housingType = step2.housing_type ?? step3.housing_type ?? null;
    // Pre-Phase-H legacy: ownership_type fallback of last resort.
    state.ownershipType = step2.ownership_type ?? step3.ownership_type ?? null;
    // Phase 3.X-fix-19: gate the Step 5 BESS placeholder row on the
    // same has_bess flag the Step 3 page reads (both come from
    // /api/profile, which fix-18 extended).
    state.hasBess = !!step2.has_bess;

    // Seed placed positions from Step 3's device arrays.
    for (const [name, arr] of Object.entries(step3.devices)) {
      if (name === "base_load") continue;
      if (!Array.isArray(arr)) continue;
      // v3.X-fix-5a-patch: name carries the engine's `#1` suffix; the
      // catalog is keyed by base type, so strip before looking up.
      const catalogMeta = DEVICE_CATALOG[stripInstanceSuffix(name)];
      if (!catalogMeta) continue;
      const bounds = VECCompute.extractBounds(arr);
      const start = bounds ? bounds.start : (catalogMeta.default_start ?? 0);
      const duration = bounds ? bounds.duration : (catalogMeta.default_duration ?? 4);
      const load_kw = catalogMeta.load_kw ?? (bounds ? arr[bounds.start] : 1.0);
      const pos = { start, duration, load_kw };
      state.originalPositions[name] = { ...pos };
      state.placed[name] = { ...pos };
      // v3.X-fix-3: willing defaults to null (= "not yet answered"),
      // not true. Submit now requires every device to be explicitly
      // answered, so an opt-in default would silently bypass the gate.
      state.willingness[name] = { willing: null, reasons: new Set() };
    }

    // Pull the Step 3 bills so the comparison strip matches what Step 4 showed.
    await loadReferenceBills();

    renderTimeline();
    renderDeviceCards();
    refreshChart();
  }

  async function loadReferenceBills() {
    // There's no dedicated GET endpoint for bills by step; re-using
    // /api/bill-comparison (returns the latest of each scenario) works.
    try {
      const resp = await fetch(`/api/bill-comparison/${state.sessionId}`);
      if (resp.ok) {
        const bills = await resp.json();
        state.bills.noVec = bills.no_vec || null;
        state.bills.vecNoAdjust = bills.vec_no_adjust || null;
      }
    } catch (err) {
      console.warn("bill-comparison fetch failed", err);
    }
  }

  // v3.6 helpers — Step 5 counterfactual + perceived-effort questions.
  function getCounterfactualAnswers() {
    const q1El = document.querySelector('input[name="step5-q1-counterfactual"]:checked');
    const q2El = document.querySelector('input[name="step5-q2-effort"]:checked');
    return {
      q1: q1El ? q1El.value : null,
      q2: q2El ? q2El.value : null,
    };
  }

  function updateConfirmEnabled() {
    // Confirm enables once:
    //  (a) both counterfactual questions are answered, AND
    //  (b) [v3.X-fix-3] every rendered device has an explicit willing
    //      yes/no. willing=null means "not yet answered" — either
    //      initial page load (default is now null, not true), or the
    //      user just dragged a device which clears its prior answer.
    const { q1, q2 } = getCounterfactualAnswers();
    // Length guard: setupCounterfactualGate fires updateConfirmEnabled
    // on page load before loadInitial has populated state.willingness.
    // Without this, Object.values({}).every(...) is vacuously true and
    // a fast user answering counterfactual mid-load could briefly see
    // Submit enabled.
    const willEntries = Object.values(state.willingness);
    const allDevicesAnswered =
      willEntries.length > 0 &&
      willEntries.every((w) => w.willing === true || w.willing === false);
    const btn = $("btn-confirm");
    if (btn) btn.disabled = !(q1 && q2 && allDevicesAnswered);
  }

  function setupCounterfactualGate() {
    document.querySelectorAll(
      'input[name="step5-q1-counterfactual"], input[name="step5-q2-effort"]'
    ).forEach((radio) => {
      radio.addEventListener("change", updateConfirmEnabled);
    });
    updateConfirmEnabled();  // initial state (both null → disabled)
  }

  // ---- Buttons ----
  function setupButtons() {
    $("btn-reset").addEventListener("click", () => {
      for (const [name, pos] of Object.entries(state.originalPositions)) {
        state.placed[name] = { ...pos };
      }
      for (const name in state.willingness) {
        // v3.X-fix-3: reset to fresh-page-load semantics — willing must
        // be re-answered after a reset, same as on first load.
        state.willingness[name] = { willing: null, reasons: new Set() };
      }
      renderTimeline();
      renderDeviceCards();
      refreshChart();
      // v3.X-fix-3: re-disable Submit until the user re-answers willing
      // for every device (renderDeviceCards rebuilt unchecked radios but
      // doesn't touch the button's disabled attribute).
      updateConfirmEnabled();
    });

    $("btn-confirm").addEventListener("click", async () => {
      const btn = $("btn-confirm");
      const errEl = $("step5-cf-error");
      if (errEl) errEl.textContent = "";

      // Defensive: button is disabled until both Qs are answered, but
      // re-check in case of synthetic clicks.
      const { q1: cf_q1, q2: cf_q2 } = getCounterfactualAnswers();
      if (!cf_q1 || !cf_q2) {
        if (errEl) errEl.textContent = "Please answer both questions about your experience.";
        return;
      }

      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        // v3.X-fix-2: writeback semantics.
        //   willing=yes → write the user's adjusted position
        //                 (shiftedPositions, falling back to baseline if the
        //                 user never dragged it).
        //   willing=no  → ALWAYS write step 3 baseline regardless of what
        //                 state.placed currently shows. This keeps the
        //                 research data clean: an "I won't shift this"
        //                 answer should land in device_shifts as the
        //                 user's natural step-3 schedule, not whatever
        //                 the chart happened to show before they decided.
        // Same rule applied to the recalculate POST below so the
        // persisted Step 5 profile / bills stay consistent with
        // device_shifts.
        function writePosFor(name) {
          const will = state.willingness[name];
          if (will && !will.willing) return state.originalPositions[name];
          return state.shiftedPositions[name] || state.originalPositions[name];
        }

        // Persist each device's shift + willingness. The FIRST shift
        // call also carries the v3.6 counterfactual + effort answers
        // (piggyback pattern, same as Step 3's prior_expectation_pct).
        const shiftCalls = [];
        let firstShiftSent = false;
        for (const name of Object.keys(state.placed)) {
          const orig = state.originalPositions[name];
          const pos = writePosFor(name) || state.placed[name];
          const will = state.willingness[name];
          const reasons = will.willing ? null : Array.from(will.reasons).join(",") || null;
          const payload = {
            session_id: state.sessionId,
            step: STEP,
            device_name: name,
            original_start: orig ? orig.start : 0,
            original_end: orig ? orig.start + orig.duration : 0,
            final_start: pos.start,
            final_end: pos.start + pos.duration,
            willing: will.willing,
            unwilling_reason: reasons,
          };
          if (!firstShiftSent) {
            payload.step5_q1_counterfactual = cf_q1;
            payload.step5_q2_effort = cf_q2;
            firstShiftSent = true;
          }
          shiftCalls.push(VECApi.saveDeviceShift(payload));
        }
        await Promise.all(shiftCalls);

        // Persist the step-5 profile + bills on the server.
        await VECApi.recalculate({
          session_id: state.sessionId,
          step: STEP,
          scenario: "vec_adjusted",
          device_positions: Object.entries(state.placed).map(([name]) => {
            const pos = writePosFor(name) || state.placed[name];
            return {
              name,
              start_slot: pos.start,
              duration_slots: pos.duration,
              load_kw: pos.load_kw,
            };
          }),
        });

        // Phase 4-A: compare Dash page renamed step6 → step5 in the
        // 7-step flow.
        window.location.href = `/dash/step5?session_id=${state.sessionId}`;
      } catch (err) {
        console.error(err);
        showError("Something went wrong while saving. Please try again.");
        btn.disabled = false;
        // Phase 4-A: next page (compare) is Step 5 in the new 7-step
        // flow (was Step 6).
        btn.textContent = "Confirm → Step 5";
      }
    });
  }

  function renderProgressBar() {
    // Phase 4-A: 7-step flow (Step 0 + Steps 1..7). The respond page
    // is Step 4 — active here. Mirrors pages/_helpers.py::make_progress
    // so static HTML and Dash pages render identical progress bars.
    const steps = ["0. Welcome", "1. Role", "2. Customize", "3. Prices",
                   "4. Respond", "5. Compare", "6. Impacts", "7. Survey"];
    const ACTIVE = 4;
    const el = $("progress-bar");
    el.innerHTML = steps.map((label, i) => {
      const cls = i < ACTIVE ? "bg-success"
                : i === ACTIVE ? "bg-primary"
                : "bg-secondary";
      return `<span class="badge ${cls} me-1">${label}</span>`;
    }).join("");
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderProgressBar();
    setupCounterfactualGate();
    setupButtons();
    loadInitial();
  });

  // Phase J: BFCache restore. Mirrors timeline.js — when the user
  // presses Back from /dash/step5 (compare page) the browser may
  // serve /step5 from BFCache with btn-confirm stuck at "Saving…"
  // disabled. Reset transient submit-cycle UI on BFCache restore.
  // Unlike timeline.js we DO call updateConfirmEnabled() here because
  // step5 already exposes a public disable-state evaluator — that
  // restores correct disabled state based on counterfactual answers
  // + willingness selections preserved by BFCache, without forcing
  // the button enabled on an incomplete form.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    const btn = document.getElementById("btn-confirm");
    if (btn) btn.textContent = "Confirm → Step 5";
    const err = document.getElementById("step5-cf-error");
    if (err) err.textContent = "";
    if (typeof updateConfirmEnabled === "function") {
      updateConfirmEnabled();
    }
  });
})();
