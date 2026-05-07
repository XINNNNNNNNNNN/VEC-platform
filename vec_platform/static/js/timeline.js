// Step 3 UI: draggable timeline, live-updated Plotly chart, live bill card.
// Depends on /static/js/api.js, /static/js/devices.js, /static/js/shared.js.

(() => {
  const STEP = 3;

  // UI state
  const state = {
    sessionId: null,
    rawBaseLoad: null,       // [96] un-scaled rigid load (Step 2 baseline)
    baseLoad: null,          // [96] scaled rigid load (= rawBaseLoad * scaleFactor)
    pvGeneration: null,      // [96]
    originalBill: null,      // Step 2 no_vec bill, for delta display
    originalPositions: {},   // { name: {start, duration, load_kw} } at Step 2 baseline
    placed: {},              // { name: {start, duration, load_kw} } currently on timeline
    // v3.4 baseline ±10% adjuster, in 5% steps. Affects only base load,
    // not PV generation or shiftable devices.
    scaleFactor: 1.0,
  };

  // ---- DOM helpers ----
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

  function renderTimeline() {
    const container = $("timeline");
    container.innerHTML = "";
    container.appendChild(renderAxis());

    // Rigid base-load row: one non-draggable block spanning the whole day,
    // annotated with morning/evening peak highlights via text.
    const rigidRow = document.createElement("div");
    rigidRow.className = "timeline-row rigid";
    const rigidLabel = document.createElement("div");
    rigidLabel.className = "timeline-row-label";
    rigidLabel.textContent = "Base load (fridge / lighting / peaks)";
    rigidRow.appendChild(rigidLabel);
    container.appendChild(rigidRow);

    // One row per placed device instance, in a stable order so the
    // visual doesn't jump. Order is base-type order × instance number.
    // v3.X-fix-5b: expand each base to up to MAX_INSTANCES_PER_BASE
    // rows so users can see / drag multiple cookings, dishwashers, etc.
    const order = ["cooking", "dishwasher", "washing_machine",
                   "dryer", "oven_baking", "ev_charger"];

    for (const baseName of order) {
      for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
        const name = `${baseName}#${n}`;
        if (!(name in state.placed)) continue;
        const row = document.createElement("div");
        row.className = "timeline-row";

        const rowLabel = document.createElement("div");
        rowLabel.className = "timeline-row-label";
        rowLabel.textContent = getDeviceLabel(name, state.placed);
        row.appendChild(rowLabel);

        const block = makeBlock(name);
        row.appendChild(block);

        container.appendChild(row);
      }
    }
  }

  function makeBlock(name) {
    const meta = DEVICE_CATALOG[stripInstanceSuffix(name)];
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

    // Phase 3.X-fix-17: timeline block × removed; users use the × in the
    // My devices list (above the timeline). Single delete entry point.

    updateBlockLabel(block, name);

    if (meta.draggable) attachDrag(block, name);
    return block;
  }

  function updateBlockLabel(block, name) {
    const pos = state.placed[name];
    // v3.X-fix-5b: tooltip uses getDeviceLabel so multi-instance blocks
    // are distinguishable on hover.
    const friendly = getDeviceLabel(name, state.placed);
    block.title = `${friendly} · ${pos.load_kw} kW · ${rangeLabel(pos.start, pos.duration)}`;
    const label = block.querySelector(".device-block-label");
    if (label) label.textContent = rangeLabel(pos.start, pos.duration);
  }

  // ---- Drag handling ----
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
        refreshChartAndBill();
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

  // ---- Add / remove ----
  function addDevice(baseName) {
    // v3.X-fix-5a-patch: dropdown options carry the bare type name; state
    // keying uses a suffixed instance key so device_shifts.device_name
    // sent to the backend matches what the engine produced for baseline
    // entries (cooking#1, etc.).
    // v3.X-fix-5b: pick the lowest free `#N` slot (up to MAX_…) so users
    // can add up to 3 instances per type. Reuses freed slots after ×.
    const name = nextStateKeyForBase(baseName, state.placed);
    if (name === null) return;  // cap reached — UI also disables option
    const meta = DEVICE_CATALOG[baseName];
    if (!meta) return;
    const defaults = state.originalPositions[name] || {
      start: meta.default_start,
      duration: meta.default_duration,
      load_kw: meta.load_kw,
    };
    state.placed[name] = { ...defaults };
    VECApi.logDrag({
      session_id: state.sessionId,
      step: STEP,
      device_name: name,
      from_start: 0,
      from_end: 0,
      to_start: defaults.start,
      to_end: defaults.start + defaults.duration,
      action: "add",
    }).catch((err) => console.warn("drag-log failed", err));
    renderTimeline();
    renderDeviceList();
    renderAddSelect();
    refreshChartAndBill();
  }

  function removeDevice(name) {
    if (!(name in state.placed)) return;
    const pos = state.placed[name];
    VECApi.logDrag({
      session_id: state.sessionId,
      step: STEP,
      device_name: name,
      from_start: pos.start,
      from_end: pos.start + pos.duration,
      to_start: 0,
      to_end: 0,
      action: "remove",
    }).catch((err) => console.warn("drag-log failed", err));
    delete state.placed[name];
    renderTimeline();
    renderDeviceList();
    renderAddSelect();
    refreshChartAndBill();
  }

  // ---- Phase 3.7-pre: My devices list + Add dropdown ----
  // Render order shared with renderTimeline() so the list and the
  // timeline visually agree.
  const DEVICE_LIST_ORDER = ["cooking", "dishwasher", "washing_machine",
                             "dryer", "oven_baking", "ev_charger"];

  function renderDeviceList() {
    const ul = $("device-instance-list");
    if (!ul) return;
    ul.innerHTML = "";
    // v3.X-fix-5b: list each instance #1..MAX_INSTANCES_PER_BASE per
    // base type. Replaces the fix-5a-patch (baseName, stateKey) pair
    // approach which only saw the first instance.
    const items = [];  // [(baseName, name), ...]
    for (const baseName of DEVICE_LIST_ORDER) {
      for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
        const name = `${baseName}#${n}`;
        if (name in state.placed) items.push([baseName, name]);
      }
    }
    if (items.length === 0) {
      const empty = document.createElement("li");
      empty.className = "device-instance-empty";
      empty.textContent = "No devices configured. Use [+ Add] below.";
      ul.appendChild(empty);
      return;
    }
    for (const [baseName, name] of items) {
      const meta = DEVICE_CATALOG[baseName];
      const pos = state.placed[name];
      const li = document.createElement("li");
      li.className = "device-instance";
      li.dataset.device = name;

      const swatch = document.createElement("span");
      swatch.className = "device-color-swatch";
      swatch.style.background = meta.color;
      li.appendChild(swatch);

      const label = document.createElement("span");
      label.className = "device-instance-label";
      const friendly = getDeviceLabel(name, state.placed);
      label.textContent = `${friendly} · ${pos.load_kw} kW · ${rangeLabel(pos.start, pos.duration)}`;
      li.appendChild(label);

      const removeBtn = document.createElement("button");
      removeBtn.className = "device-remove-btn";
      removeBtn.type = "button";
      removeBtn.textContent = "×";
      removeBtn.title = `Remove ${friendly}`;
      removeBtn.addEventListener("click", () => removeDevice(name));
      li.appendChild(removeBtn);

      ul.appendChild(li);
    }
  }

  function renderAddSelect() {
    const select = $("add-device-select");
    const btn = $("add-device-btn");
    if (!select || !btn) return;
    const previous = select.value;
    select.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Add a device…";
    select.appendChild(placeholder);

    // v3.X-fix-5b: keep every draggable type in the dropdown; disable
    // an option once the user has hit MAX_INSTANCES_PER_BASE for that
    // type, and annotate "(currently N)" / "(max 3 reached)" so the
    // dropdown explains why a type can't be added again.
    let addable = 0;
    for (const baseName of DEVICE_LIST_ORDER) {
      const meta = DEVICE_CATALOG[baseName];
      if (!meta || !meta.draggable) continue;
      const present = countInstancesOfBase(baseName, state.placed);
      const opt = document.createElement("option");
      opt.value = baseName;        // dropdown carries the bare type;
                                   // addDevice() suffixes it on insert.
      if (present >= MAX_INSTANCES_PER_BASE) {
        opt.disabled = true;
        opt.textContent = `${meta.label} (max ${MAX_INSTANCES_PER_BASE} reached)`;
      } else if (present >= 1) {
        opt.textContent = `${meta.label} (add another, currently ${present})`;
        addable++;
      } else {
        opt.textContent = meta.label;
        addable++;
      }
      select.appendChild(opt);
    }
    select.disabled = addable === 0;
    const count = addable;  // preserve original variable name for the
                            // initial-button-state branch below.
    // Re-select previous choice if still in the dropdown (could have been
    // removed by an earlier addDevice).
    if (previous && [...select.options].some((o) => o.value === previous)) {
      select.value = previous;
    }
    // Enable Add button only when a device type is actually selected.
    btn.disabled = count === 0 || !select.value;
  }

  // ---- Chart ----

  function hours() {
    const out = new Array(SLOTS_PER_DAY);
    for (let i = 0; i < SLOTS_PER_DAY; i++) out[i] = (i * 15) / 60;
    return out;
  }

  function buildTraces(deviceArrays) {
    const x = hours();
    const traces = [];
    // Base load first (bottom of stack). It's not in state.placed —
    // it's the rigid background load — so it gets its own trace from
    // state.baseLoad / DEVICE_CATALOG.base_load metadata.
    traces.push({
      x, y: state.baseLoad,
      name: DEVICE_CATALOG.base_load.label,
      mode: "lines",
      stackgroup: "load",
      line: { width: 0.5, color: DEVICE_CATALOG.base_load.color },
      hovertemplate: "%{y:.2f} kW<extra>Base load</extra>",
    });
    // Phase 3.7-pre patch: iterate the same canonical order used by the
    // device list and the timeline rows, filtered to whatever the user
    // currently has in state.placed (which is mirrored in deviceArrays).
    // Picks up user-added types (dryer, oven_baking) automatically and
    // drops removed ones.
    // v3.X-fix-5b: expand each base to its #1..MAX_INSTANCES_PER_BASE
    // instances so multi-instance setups stack correctly. Trace name
    // uses getDeviceLabel so the legend differentiates "Stove (cooking)"
    // from "Stove (cooking) #2".
    for (const baseName of DEVICE_LIST_ORDER) {
      const meta = DEVICE_CATALOG[baseName];
      if (!meta) continue;  // defensive: unknown device type
      for (let n = 1; n <= MAX_INSTANCES_PER_BASE; n++) {
        const name = `${baseName}#${n}`;
        if (!(name in deviceArrays)) continue;
        const traceLabel = getDeviceLabel(name, state.placed);
        traces.push({
          x, y: deviceArrays[name],
          name: traceLabel,
          mode: "lines",
          stackgroup: "load",
          line: { width: 0.5, color: meta.color },
          hovertemplate: `%{y:.2f} kW<extra>${traceLabel}</extra>`,
        });
      }
    }
    const hasPv = state.pvGeneration.some((v) => v > 0);
    if (hasPv) {
      traces.push({
        x,
        y: state.pvGeneration.map((v) => -v),
        name: "PV generation",
        mode: "lines",
        stackgroup: "pv",
        line: { width: 0.5, color: "#f1c40f" },
        fillcolor: "rgba(241, 196, 15, 0.5)",
        hovertemplate: "%{y:.2f} kW<extra>PV</extra>",
      });
    }
    // Net load line on top.
    const netLoad = VECCompute.computeNetLoad(state.baseLoad, deviceArrays, state.pvGeneration);
    traces.push({
      x, y: netLoad,
      name: "Net load",
      mode: "lines",
      line: { color: "#000", width: 2, dash: "dot" },
      hovertemplate: "%{y:.2f} kW<extra>Net load</extra>",
    });
    return { traces, netLoad };
  }

  function refreshChartAndBill() {
    const deviceArrays = VECCompute.buildDeviceArrays(state.placed);
    const { traces, netLoad } = buildTraces(deviceArrays);
    const layout = {
      margin: { l: 50, r: 20, t: 20, b: 40 },
      xaxis: {
        title: "Hour of day",
        tickmode: "array",
        tickvals: [0, 3, 6, 9, 12, 15, 18, 21, 24],
        range: [0, 24],
      },
      yaxis: { title: "Power (kW)" },
      legend: { orientation: "h", yanchor: "bottom", y: -0.35 },
      hovermode: "x unified",
    };
    Plotly.react("load-chart", traces, layout, { displayModeBar: false });

    const bill = VECCompute.computeBillScenario(netLoad, "no_vec");
    renderBillCard(bill);
  }

  function renderBillCard(bill) {
    const el = $("bill-card");
    const orig = state.originalBill;
    const delta = orig ? bill.net_cost - orig.net_cost : null;
    const deltaCls = delta === null ? "" : (delta > 0.5 ? "positive" : delta < -0.5 ? "negative" : "");
    const deltaStr = delta === null ? "" :
      `<span class="bill-delta ${deltaCls}">(${delta >= 0 ? "+" : ""}${delta.toFixed(0)} SEK vs. baseline)</span>`;

    function row(label, value) {
      return `<div class="bill-row"><span>${label}</span><span>${value.toLocaleString("en-US", { maximumFractionDigits: 0 })} SEK</span></div>`;
    }

    el.innerHTML = `
      ${row("Electricity purchase", bill.energy_purchase)}
      ${row("Grid fee", bill.grid_fee)}
      ${row("Energy tax", bill.energy_tax)}
      ${row("Feed-in income", -bill.feed_in_income)}
      <div class="bill-row total"><span>Net cost</span><span>${bill.net_cost.toLocaleString("en-US", { maximumFractionDigits: 0 })} SEK ${deltaStr}</span></div>
      <div class="text-muted small mt-2">Monthly estimate (typical day × 30).</div>
    `;
  }

  // ---- Initial data load ----
  async function loadInitial() {
    state.sessionId = VECApi.getSessionId();
    if (!state.sessionId) {
      showError("No session_id in the URL. Please start from Step 1.");
      return;
    }
    $("session-label").textContent = `Session: ${state.sessionId.slice(0, 8)}…`;

    let profile;
    try {
      profile = await VECApi.getProfile(state.sessionId, 2);
    } catch (err) {
      showError("Failed to load your Step 2 profile. Please complete Step 1 & 2 first.");
      console.error(err);
      return;
    }

    state.rawBaseLoad = profile.rigid_load;
    state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
    state.pvGeneration = profile.pv_generation;

    // Seed positions: for every device present in the Step 2 profile, pick a
    // start/duration. Prefer JS defaults (they match MockEngine), but fall
    // back to extracting bounds from the raw array for any unknown device.
    for (const [name, arr] of Object.entries(profile.devices)) {
      if (name === "base_load") continue;
      if (!Array.isArray(arr)) continue;
      // v3.X-fix-5a-patch: name carries the engine's `#1` suffix; the
      // catalog is keyed by base type, so strip before looking up.
      const catalogMeta = DEVICE_CATALOG[stripInstanceSuffix(name)];
      if (!catalogMeta) continue;
      const bounds = VECCompute.extractBounds(arr);
      const start = catalogMeta.default_start ?? (bounds ? bounds.start : 0);
      const duration = catalogMeta.default_duration ?? (bounds ? bounds.duration : 4);
      const load_kw = catalogMeta.load_kw ?? (bounds ? arr[bounds.start] : 1.0);
      const pos = { start, duration, load_kw };
      state.originalPositions[name] = { ...pos };
      state.placed[name] = { ...pos };
    }

    // Original bill for delta comparison: compute from Step 2's net_load directly.
    state.originalBill = VECCompute.computeBillScenario(profile.net_load, "no_vec");

    renderTimeline();
    renderDeviceList();
    renderAddSelect();
    refreshChartAndBill();
  }

  // ---- v3.4: baseline scale (±10%) ----
  function applyScale(arr, factor) {
    return arr.map((v) => v * factor);
  }

  function updateScaleDisplay() {
    const pct = Math.round((state.scaleFactor - 1.0) * 100);
    const sign = pct > 0 ? "+" : "";
    $("scale-display").textContent = `${sign}${pct}%`;
    // Disable buttons at the bounds.
    $("scale-decrement").disabled = state.scaleFactor <= 0.9001;  // float fudge
    $("scale-increment").disabled = state.scaleFactor >= 1.0999;
  }

  function setScaleFactor(newFactor) {
    state.scaleFactor = +newFactor.toFixed(2);
    state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
    updateScaleDisplay();
    refreshChartAndBill();
  }

  function setupScaleControls() {
    $("scale-decrement").addEventListener("click", () => {
      setScaleFactor(Math.max(0.9, state.scaleFactor - 0.05));
    });
    $("scale-increment").addEventListener("click", () => {
      setScaleFactor(Math.min(1.1, state.scaleFactor + 0.05));
    });
    updateScaleDisplay();
  }

  // ---- v3.4: end-of-Step-3 questions (second prior expectation + confidence) ----
  function setupQuestionControls() {
    // Live "X%" label below the slider.
    $("step3-expectation-pct").addEventListener("input", (e) => {
      $("step3-expectation-display").textContent = e.target.value;
    });
    // Likert change → enable Confirm.
    document.querySelectorAll('input[name="step3-confidence"]').forEach((radio) => {
      radio.addEventListener("change", () => {
        $("btn-confirm").disabled = false;
      });
    });
  }

  function getQuestionAnswers() {
    const checked = document.querySelector('input[name="step3-confidence"]:checked');
    return {
      pct: Number($("step3-expectation-pct").value),
      confidence: checked ? Number(checked.value) : null,
    };
  }

  // ---- Buttons ----
  function setupButtons() {
    $("btn-reset").addEventListener("click", () => {
      state.placed = {};
      for (const [name, pos] of Object.entries(state.originalPositions)) {
        state.placed[name] = { ...pos };
      }
      renderTimeline();
      renderDeviceList();
      renderAddSelect();
      refreshChartAndBill();
    });

    // Phase 3.7-pre: Add device dropdown wiring.
    const addSelect = $("add-device-select");
    const addBtn = $("add-device-btn");
    if (addSelect && addBtn) {
      // Enable the Add button only when a device type is actually picked.
      addSelect.addEventListener("change", () => {
        addBtn.disabled = !addSelect.value;
      });
      addBtn.addEventListener("click", () => {
        const name = addSelect.value;
        if (!name) return;
        addDevice(name);  // single-instance: addDevice no-ops if already placed
        addSelect.value = "";
        addBtn.disabled = true;
      });
    }

    $("btn-confirm").addEventListener("click", async () => {
      const btn = $("btn-confirm");
      const errEl = $("step3-error");
      errEl.textContent = "";

      // Confidence must be picked (button is normally disabled until it is,
      // but defend against synthetic clicks / race conditions).
      const { pct, confidence } = getQuestionAnswers();
      if (confidence === null) {
        errEl.textContent = "Please answer the confidence question.";
        return;
      }

      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        // Persist each device shift vs. its Step 2 baseline position. The
        // FIRST shift call also carries the second prior-expectation guess
        // and the confidence Likert — backend writes a PriorExpectation
        // row (round=2) when both are present and step == 3.
        //
        // v3.X-fix-5c: iterate the union of state-key names actually in
        // use, not DEVICE_CATALOG bare names. Pre-fix-5a the catalog
        // keys (`cooking`, `dishwasher`, ...) lined up with state.placed
        // / state.originalPositions; post-fix-5a state keys carry a `#N`
        // suffix (cooking#1, cooking#2, ...) so the bare-name iteration
        // missed every instance and silently dropped all device-shift
        // POSTs. Union covers three cases:
        //   - loaded baseline still placed (orig + placed both present)
        //   - loaded baseline removed by × (orig only; final = 0)
        //   - user-added instance (placed only; original = 0)
        const shiftNames = new Set([
          ...Object.keys(state.originalPositions),
          ...Object.keys(state.placed),
        ]);
        const shifts = [];
        let firstShiftSent = false;
        for (const name of shiftNames) {
          const orig = state.originalPositions[name];
          const placed = state.placed[name];
          if (!orig && !placed) continue;  // defensive — set above can't yield this
          const origStart = orig ? orig.start : 0;
          const origEnd = orig ? orig.start + orig.duration : 0;
          const finalStart = placed ? placed.start : 0;
          const finalEnd = placed ? placed.start + placed.duration : 0;
          const payload = {
            session_id: state.sessionId,
            step: STEP,
            device_name: name,
            original_start: origStart,
            original_end: origEnd,
            final_start: finalStart,
            final_end: finalEnd,
          };
          if (!firstShiftSent) {
            payload.prior_expectation_pct = pct;
            payload.confidence = confidence;
            firstShiftSent = true;
          }
          shifts.push(VECApi.saveDeviceShift(payload));
        }
        await Promise.all(shifts);

        // Persist the step=3 profile + bills server-side. scale_factor
        // is sent so the backend can stash it in daily_profiles.devices
        // (under the __scale_factor__ key) and apply the same scaling
        // to the rigid base load.
        await VECApi.recalculate({
          session_id: state.sessionId,
          step: STEP,
          scenario: "no_vec",
          scale_factor: state.scaleFactor,
          device_positions: Object.entries(state.placed).map(([name, pos]) => ({
            name,
            start_slot: pos.start,
            duration_slots: pos.duration,
            load_kw: pos.load_kw,
          })),
        });

        window.location.href = `/dash/step4?session_id=${state.sessionId}`;
      } catch (err) {
        console.error(err);
        showError("Something went wrong while saving your choices. Please try again.");
        btn.disabled = false;
        btn.textContent = "Next";
      }
    });
  }

  function renderProgressBar() {
    const steps = ["1. Role", "2. Profile", "3. Customize", "4. Prices",
                   "5. Respond", "6. Compare", "7. Impacts", "8. Survey"];
    const el = $("progress-bar");
    el.innerHTML = steps.map((label, i) => {
      const n = i + 1;
      const cls = n < 3 ? "bg-success" : n === 3 ? "bg-primary" : "bg-secondary";
      return `<span class="badge ${cls} me-1">${label}</span>`;
    }).join("");
  }

  // ---- Bootstrap ----
  document.addEventListener("DOMContentLoaded", () => {
    renderProgressBar();
    setupScaleControls();
    setupQuestionControls();
    setupButtons();
    loadInitial();
  });
})();
