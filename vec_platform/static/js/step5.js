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
    step2NetLoad: null,
    step3NetLoad: null,
    originalPositions: {},     // Step 3 positions, the starting point
    placed: {},                // Live positions in Step 5
    willingness: {},           // { name: { willing: bool, reasons: Set<string> } }
    bills: {
      noVec: null,             // Step 3 no_vec baseline (for "without VEC" column)
      vecNoAdjust: null,       // Step 3 vec_no_adjust (for "VEC, same schedule")
    },
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

    for (const name of DEVICE_ROW_ORDER) {
      if (!(name in state.placed)) continue;
      const row = document.createElement("div");
      row.className = "timeline-row";

      const rowLabel = document.createElement("div");
      rowLabel.className = "timeline-row-label";
      rowLabel.textContent = DEVICE_CATALOG[name].label;
      row.appendChild(rowLabel);

      row.appendChild(makeBlock(name));
      container.appendChild(row);
    }
  }

  function makeBlock(name) {
    const meta = DEVICE_CATALOG[name];
    const pos = state.placed[name];
    const block = document.createElement("div");
    block.className = "device-block";
    block.dataset.device = name;
    block.style.background = meta.color;
    block.style.left = `${(pos.start / SLOTS_PER_DAY) * 100}%`;
    block.style.width = `${(pos.duration / SLOTS_PER_DAY) * 100}%`;

    const labelSpan = document.createElement("span");
    labelSpan.className = "device-block-label";
    block.appendChild(labelSpan);
    updateBlockLabel(block, name);

    if (meta.draggable) attachDrag(block, name);
    return block;
  }

  function updateBlockLabel(block, name) {
    const meta = DEVICE_CATALOG[name];
    const pos = state.placed[name];
    block.title = `${meta.label} · ${pos.load_kw} kW · ${rangeLabel(pos.start, pos.duration)}`;
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
      const duration = state.placed[name].duration;
      const newStart = VECCompute.clampStart(startSlotAtPointerDown + dSlots, duration);
      if (newStart !== state.placed[name].start) {
        state.placed[name].start = newStart;
        block.style.left = `${(state.placed[name].start / SLOTS_PER_DAY) * 100}%`;
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
    for (const name of DEVICE_ROW_ORDER) {
      if (!(name in state.placed)) continue;
      root.appendChild(makeDeviceCard(name));
    }
  }

  function makeDeviceCard(name) {
    const meta = DEVICE_CATALOG[name];
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
    nameSpan.textContent = meta.label;
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
    const card = $("device-cards").querySelector(`.device-card[data-device="${name}"]`);
    if (!card) return;
    const reasons = card.querySelector("[data-role=reasons]");
    if (willing) {
      reasons.classList.add("hidden");
      // Uncheck all boxes visually.
      reasons.querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = false; });
    } else {
      reasons.classList.remove("hidden");
    }
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
        name: "Step 2 — baseline",
        mode: "lines",
        line: { color: "#adb5bd", width: 1.5, dash: "dash" },
        hovertemplate: "%{y:.2f} kW<extra>Baseline</extra>",
      },
      {
        x, y: state.step3NetLoad,
        name: "Step 3 — your first pass",
        mode: "lines",
        line: { color: "#3498db", width: 2 },
        hovertemplate: "%{y:.2f} kW<extra>Step 3</extra>",
      },
      {
        x, y: netNow,
        name: "Step 5 — after responding",
        mode: "lines",
        line: { color: "#27ae60", width: 2.5 },
        hovertemplate: "%{y:.2f} kW<extra>Step 5 live</extra>",
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
    const adjusted = VECCompute.computeBillScenario(netNow, "vec_adjusted");

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
    $("btn-back").href = `/dash/step4?session_id=${state.sessionId}`;

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

    // Seed placed positions from Step 3's device arrays.
    for (const [name, arr] of Object.entries(step3.devices)) {
      if (name === "base_load") continue;
      if (!Array.isArray(arr)) continue;
      const catalogMeta = DEVICE_CATALOG[name];
      if (!catalogMeta) continue;
      const bounds = VECCompute.extractBounds(arr);
      const start = bounds ? bounds.start : (catalogMeta.default_start ?? 0);
      const duration = bounds ? bounds.duration : (catalogMeta.default_duration ?? 4);
      const load_kw = catalogMeta.load_kw ?? (bounds ? arr[bounds.start] : 1.0);
      const pos = { start, duration, load_kw };
      state.originalPositions[name] = { ...pos };
      state.placed[name] = { ...pos };
      state.willingness[name] = { willing: true, reasons: new Set() };
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

  // ---- Buttons ----
  function setupButtons() {
    $("btn-reset").addEventListener("click", () => {
      for (const [name, pos] of Object.entries(state.originalPositions)) {
        state.placed[name] = { ...pos };
      }
      for (const name in state.willingness) {
        state.willingness[name] = { willing: true, reasons: new Set() };
      }
      renderTimeline();
      renderDeviceCards();
      refreshChart();
    });

    $("btn-confirm").addEventListener("click", async () => {
      const btn = $("btn-confirm");
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        // Persist each device's shift + willingness.
        const shiftCalls = [];
        for (const name of Object.keys(state.placed)) {
          const orig = state.originalPositions[name];
          const pos = state.placed[name];
          const will = state.willingness[name];
          const reasons = will.willing ? null : Array.from(will.reasons).join(",") || null;
          shiftCalls.push(VECApi.saveDeviceShift({
            session_id: state.sessionId,
            step: STEP,
            device_name: name,
            original_start: orig ? orig.start : 0,
            original_end: orig ? orig.start + orig.duration : 0,
            final_start: pos.start,
            final_end: pos.start + pos.duration,
            willing: will.willing,
            unwilling_reason: reasons,
          }));
        }
        await Promise.all(shiftCalls);

        // Persist the step-5 profile + bills on the server.
        await VECApi.recalculate({
          session_id: state.sessionId,
          step: STEP,
          scenario: "vec_adjusted",
          device_positions: Object.entries(state.placed).map(([name, pos]) => ({
            name,
            start_slot: pos.start,
            duration_slots: pos.duration,
            load_kw: pos.load_kw,
          })),
        });

        window.location.href = `/dash/step6?session_id=${state.sessionId}`;
      } catch (err) {
        console.error(err);
        showError("Something went wrong while saving. Please try again.");
        btn.disabled = false;
        btn.textContent = "Confirm → Step 6";
      }
    });
  }

  function renderProgressBar() {
    const steps = ["1. Role", "2. Profile", "3. Customize", "4. Prices",
                   "5. Respond", "6. Compare", "7. Impacts", "8. Survey"];
    const el = $("progress-bar");
    el.innerHTML = steps.map((label, i) => {
      const n = i + 1;
      const cls = n < 5 ? "bg-success" : n === 5 ? "bg-primary" : "bg-secondary";
      return `<span class="badge ${cls} me-1">${label}</span>`;
    }).join("");
  }

  document.addEventListener("DOMContentLoaded", () => {
    renderProgressBar();
    setupButtons();
    loadInitial();
  });
})();
