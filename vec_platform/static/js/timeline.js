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
    // Phase 3.X-fix-18: drives the BESS placeholder track. Display-only;
    // auto-managed charge/discharge simulation is deferred.
    hasBess: false,
    // Phase B: drive conditional rendering of the calibration panel's
    // capacity rows (PV / BESS / EV). All fetched from /api/profile.
    hasPv: false,
    hasEv: false,
    // Phase 3.X-fix-19: SE3 summer retail-price array (96 slots). Used
    // to compute the BESS placeholder charge/discharge windows. Fetched
    // alongside the profile.
    spotPrices: null,
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

    // Phase 3.X-fix-18: BESS placeholder track. Rendered only when the
    // session's user_inputs.has_bess is true. Display-only — no drag,
    // no charge/discharge simulation. Auto-managed dispatch will be
    // added in a later refactor phase.
    // Phase 3.X-fix-19: row body now shows 96 slots tinted by the
    // charge / discharge schedule derived from spot prices.
    if (state.hasBess) {
      container.appendChild(VECBessUI.makeRow(state.spotPrices));
    }

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

        // Phase 3.X-fix-18: makeBlock returns one segment for normal
        // devices, two for those whose configured run wraps midnight.
        for (const block of makeBlock(name)) {
          row.appendChild(block);
        }

        container.appendChild(row);
      }
    }
  }

  // Phase 3.X-fix-18: returns [tail, head] (two divs) when the device's
  // configured run crosses midnight, otherwise [singleBlock]. Both
  // segments share the same `name` and (for draggable devices) the same
  // drag handler keyed on `name`, so dragging either segment moves the
  // device as a single logical unit.
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
      // Phase 3.X-fix-18: wrap (modulo) instead of clamp so dragging a
      // device past midnight lands it on the other side of the day.
      const newStart = VECCompute.wrapStart(startSlotAtPointerDown + dSlots);
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
      // Phase 3.X-fix-18: re-render so a wrapped device is shown as
      // two cleanly aligned segments (tail at right, head at left)
      // rather than a single block clipped at the right edge.
      renderTimeline();
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

    let profile, shadow;
    try {
      // Phase 3.X-fix-19: fetch shadow prices in parallel so the BESS
      // placeholder row can colour its 96 slots from the SE3 retail
      // curve. /api/shadow-prices is GET-creates-if-missing, so calling
      // from Step 3 is safe even though Step 4 is normally where the
      // session-level row gets created.
      // Phase D-2: prefer the user's customised profile (step=3 — the
      // last "Next" snapshot of device positions) so refreshing /step3
      // restores their drags. First-time visitors don't have a step=3
      // row yet — fall back to the step=2 baseline. The server's
      // step=3 response also pulls un-scaled rigid_load + fresh PV
      // from current calibration, so the two paths produce
      // structurally identical state for JS (only `devices` differs:
      // user's drags vs. baseline default positions).
      [profile, shadow] = await Promise.all([
        VECApi.getProfile(state.sessionId, 3).catch((e) =>
          VECApi.getProfile(state.sessionId, 2)
        ),
        VECApi.getShadowPrices(state.sessionId),
      ]);
    } catch (err) {
      showError("Failed to load your Step 2 profile. Please complete Step 1 & 2 first.");
      console.error(err);
      return;
    }

    state.rawBaseLoad = profile.rigid_load;
    state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
    state.pvGeneration = profile.pv_generation;
    // Phase 3.X-fix-18: gate the BESS placeholder track. Defaults to
    // false if the backend response predates the fix-18 schema bump.
    state.hasBess = !!profile.has_bess;
    // Phase B: drive the calibration panel's PV / EV capacity rows.
    state.hasPv = !!profile.has_pv;
    state.hasEv = !!profile.has_ev;
    // Phase 3.X-fix-19: retail price drives the BESS schedule. Fall
    // back to internal_buy if a future API rev drops retail_price.
    state.spotPrices = (shadow && (shadow.retail_price || shadow.internal_buy)) || null;

    // Seed positions: for every device present in the loaded profile,
    // pick a start/duration. Phase D-2 inverted the priority: bounds
    // extracted from the array (the user's last drag persisted at
    // step=3, or the engine's default at step=2) take precedence over
    // catalog defaults. This lets a refresh restore "where the user
    // left a device" instead of always snapping back to the
    // hard-coded catalog start. The catalog default remains as a
    // fallback for devices the engine didn't seed and arrays we
    // can't extract bounds from.
    //
    // ``state.originalPositions`` always uses the catalog defaults so
    // the Reset-to-defaults button has a stable target — restoring
    // that snapshot is what reverts the user's drags.
    for (const [name, arr] of Object.entries(profile.devices)) {
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
      // Reset target: catalog defaults (what the engine seeds at
      // step=2). Live position: bounds-first (what the user last
      // dragged to, or the catalog default on first visit).
      const defaults = {
        start: catalogMeta.default_start ?? start,
        duration: catalogMeta.default_duration ?? duration,
        load_kw,
      };
      state.originalPositions[name] = defaults;
      state.placed[name] = { start, duration, load_kw };
    }

    // Original bill for delta comparison: compute from Step 2's net_load directly.
    state.originalBill = VECCompute.computeBillScenario(profile.net_load, "no_vec");

    renderTimeline();
    renderDeviceList();
    renderAddSelect();
    refreshChartAndBill();
    // Phase B / C: wire calibration panel after profile is loaded so
    // the PV/BESS/EV row visibility reflects state.has* and Phase C
    // can restore persisted capacity values + calibrated flags.
    setupCalibrationPanel(profile);
  }

  // ---- v3.4 / Phase B: baseline scale ----
  // Phase B moved the ±5% scaling controls into the bill-card
  // calibration panel and dropped the [-10%, +10%] clamp (users can
  // adjust arbitrarily far). The scale state itself still lives on
  // `state.scaleFactor` because /api/recalculate accepts it as a
  // ready-made multiplier; only the UI wiring changed.
  function applyScale(arr, factor) {
    return arr.map((v) => v * factor);
  }

  // Phase C: capacity-input column metadata. The schema column for
  // each DER carries the historical "kWp" / "kWh" suffix; the JS DOM
  // ids are the cleaner "pv" / "bess" / "ev" prefixes.
  const _CAP_FIELDS = {
    pv:   { col: "pv_kwp",  default: 5  },
    bess: { col: "bess_kwh", default: 10 },
    ev:   { col: "ev_kwh",  default: 60 },
  };

  function setupCalibrationPanel(profile) {
    // Phase B + C: scaling buttons drive state.scaleFactor (still
    // consumed by /api/recalculate exactly as before); capacity
    // inputs are still visual-only on the bill in Phase C, but every
    // change is now persisted to user_inputs via PUT
    // /api/user_input/calibration. Phase D will switch the engine to
    // read calibration values from those columns.

    // ---- Phase C: restore state from profile ----
    if (profile && typeof profile.load_scale_factor === "number") {
      state.scaleFactor = +profile.load_scale_factor.toFixed(2);
      state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
    }

    // ---- Scaling controls ----
    const upBtn   = $("btn-scale-up");
    const downBtn = $("btn-scale-down");
    const display = $("scaling-display");
    if (upBtn && downBtn && display) {
      const updateDisplay = () => {
        const pct = Math.round((state.scaleFactor - 1.0) * 100);
        const sign = pct > 0 ? "+" : "";
        display.textContent = `${sign}${pct}%`;
      };
      const adjust = (deltaPct) => {
        // Step in 5% increments; multiplicative bound prevents the
        // load array going non-positive on extreme negative scaling.
        const stepFactor = deltaPct / 100;
        const next = +(state.scaleFactor + stepFactor).toFixed(2);
        if (next < 0.05) return;  // floor; below this base load → 0
        state.scaleFactor = next;
        state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
        updateDisplay();
        refreshChartAndBill();
        // Phase C: persist baseline scale.
        scheduleCalibrationPersist({ load_scale_factor: state.scaleFactor });
      };
      upBtn.addEventListener("click", () => adjust(+5));
      downBtn.addEventListener("click", () => adjust(-5));
      updateDisplay();
    }

    // ---- Capacity rows ----
    // Un-hide rows for DERs the participant selected on Step 1, then
    // restore each row's value + "I don't know" state from the
    // profile. Defaults from _CAP_FIELDS apply when the column is
    // NULL (fresh sessions before any calibration PUT).
    const capPresent = {
      pv:   !!state.hasPv,
      bess: !!state.hasBess,
      ev:   !!state.hasEv,
    };
    Object.entries(capPresent).forEach(([t, present]) => {
      const row = document.getElementById(`${t}-capacity-row`);
      if (row) row.style.display = present ? "" : "none";
    });

    Object.keys(_CAP_FIELDS).forEach((t) => {
      const inp = document.getElementById(`${t}-capacity-input`);
      const chk = document.getElementById(`${t}-capacity-unknown`);
      if (!inp || !chk) return;

      // ---- Phase C restore ----
      const meta = _CAP_FIELDS[t];
      const calibrated = profile && profile[`${t}_calibrated`];
      const persistedValue = profile ? profile[meta.col] : null;
      // If the column is non-NULL (step1 default-writes pv_kwp=5 and
      // bess_kwh=10) prefer that value; otherwise fall back to the
      // capDefault.
      inp.value = persistedValue != null ? persistedValue : meta.default;
      chk.checked = !calibrated;
      inp.disabled = chk.checked;

      chk.addEventListener("change", () => {
        const known = !chk.checked;
        inp.disabled = !known;
        if (!known) {
          // Reset to default. The PUT below carries the default value
          // *and* sets *_calibrated=False so analyses can split
          // "user reset to default" from "user picked default".
          inp.value = meta.default;
        }
        scheduleCalibrationPersist(buildCapacityPatch(t));
      });
      inp.addEventListener("change", () => {
        // Only persist edits when the user has confirmed (input
        // enabled). Disabled inputs can't be edited via UI but defend
        // against synthetic events.
        if (!inp.disabled) {
          scheduleCalibrationPersist(buildCapacityPatch(t));
        }
      });
    });
  }

  // Phase D-1: after a calibration write lands, pull the updated
  // baseline arrays back from /api/profile (which now re-derives PV
  // from user_inputs.pv_kwp) and refresh the live chart + bill so
  // the participant sees the effect of changing PV capacity right
  // away. Today only PV affects state.pvGeneration; BESS / EV
  // capacities will be wired in D-2 / D-3 and would extend this
  // function then.
  async function refetchBaselineAndRefresh() {
    if (!state.sessionId) return;
    let profile;
    try {
      profile = await VECApi.getProfile(state.sessionId, 2);
    } catch (err) {
      console.warn("Calibration refetch failed:", err);
      return;
    }
    state.rawBaseLoad = profile.rigid_load;
    state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);
    state.pvGeneration = profile.pv_generation;
    refreshChartAndBill();
  }

  // ---- Phase C: calibration persistence ----
  // Debounced PUT so a flurry of ±5% clicks or a fast keyboard edit
  // coalesces into one round-trip. 300 ms is comfortably below the
  // perceptual threshold for "did my change save?" feedback.
  let _calibrationPatchPending = {};
  let _calibrationTimer = null;

  function buildCapacityPatch(prefix) {
    const meta = _CAP_FIELDS[prefix];
    const inp = document.getElementById(`${prefix}-capacity-input`);
    const chk = document.getElementById(`${prefix}-capacity-unknown`);
    const known = !chk.checked;
    const raw = Number(inp.value);
    const value = Number.isFinite(raw) && raw > 0 ? raw : meta.default;
    return {
      [meta.col]: value,
      [`${prefix}_calibrated`]: known,
    };
  }

  function scheduleCalibrationPersist(patch) {
    Object.assign(_calibrationPatchPending, patch);
    if (_calibrationTimer) clearTimeout(_calibrationTimer);
    _calibrationTimer = setTimeout(persistCalibration, 300);
  }

  async function persistCalibration() {
    if (!state.sessionId) return;
    const patch = _calibrationPatchPending;
    _calibrationPatchPending = {};
    _calibrationTimer = null;
    if (Object.keys(patch).length === 0) return;
    const body = { session_id: state.sessionId, ...patch };
    let ok = false;
    try {
      const r = await fetch("/api/user_input/calibration", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      ok = r.ok;
      if (!r.ok) {
        const detail = await r.text().catch(() => "");
        console.warn("Calibration persist failed:", r.status, detail);
      }
    } catch (e) {
      console.warn("Calibration persist error:", e);
    }
    // Phase D-1: after the PUT lands, refresh the baseline so the
    // chart + bill reflect the new PV / scaling. The fix-18 ±5%
    // path already mutates state.scaleFactor + state.baseLoad in
    // memory and calls refreshChartAndBill *before* the PUT, so
    // for scaling alone this is a no-op redraw. For capacity
    // changes, it's the only path to a fresh PV curve.
    if (ok) {
      await refetchBaselineAndRefresh();
    }
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
    $("btn-reset").addEventListener("click", async () => {
      // Phase D-2: full reset. Previously this only restored device
      // positions; with calibration persistence (Phase B/C/D-1), the
      // user expects "Reset to defaults" to also clear the PV/BESS/EV
      // capacity inputs and the ±5% baseline scaler. The button
      // semantics now match its label across all of /step3.
      state.placed = {};
      for (const [name, pos] of Object.entries(state.originalPositions)) {
        state.placed[name] = { ...pos };
      }

      // Reset calibration in-memory state.
      state.scaleFactor = 1.0;
      state.baseLoad = applyScale(state.rawBaseLoad, state.scaleFactor);

      // Reset calibration UI: capacity inputs back to defaults +
      // checkboxes ticked + inputs disabled.
      Object.entries(_CAP_FIELDS).forEach(([t, meta]) => {
        const inp = document.getElementById(`${t}-capacity-input`);
        const chk = document.getElementById(`${t}-capacity-unknown`);
        if (!inp || !chk) return;
        inp.value = meta.default;
        chk.checked = true;
        inp.disabled = true;
      });
      // Reset scaling display.
      const scalingDisplay = $("scaling-display");
      if (scalingDisplay) scalingDisplay.textContent = "0%";

      // Persist defaults to user_inputs (atomic 7-field reset).
      // Cancel any pending debounced PUT first so it doesn't fire
      // after this one and re-write stale values.
      if (_calibrationTimer) {
        clearTimeout(_calibrationTimer);
        _calibrationTimer = null;
      }
      _calibrationPatchPending = {};
      try {
        const r = await fetch("/api/user_input/calibration", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: state.sessionId,
            pv_kwp: _CAP_FIELDS.pv.default,
            bess_kwh: _CAP_FIELDS.bess.default,
            ev_kwh: null,
            load_scale_factor: 1.0,
            pv_calibrated: false,
            bess_calibrated: false,
            ev_calibrated: false,
          }),
        });
        if (!r.ok) {
          const detail = await r.text().catch(() => "");
          console.warn("Reset calibration PUT failed:", r.status, detail);
        }
      } catch (e) {
        console.warn("Reset calibration PUT error:", e);
      }

      // Refresh: fetch baseline (with reset PV curve) and re-render.
      await refetchBaselineAndRefresh();
      renderTimeline();
      renderDeviceList();
      renderAddSelect();
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

        // Persist the step=3 profile + bills server-side. Phase D-1:
        // scale_factor is no longer authoritative on the request —
        // the server reads user_inputs.load_scale_factor (kept in
        // sync by the calibration PUT path) — but the field is sent
        // anyway for backward compat with the recalculate schema.
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

        // Phase 4-A: prices Dash page renamed step4 → step3 in the
        // 7-step flow. URL preserved scheme stays under /dash/.
        window.location.href = `/dash/step3?session_id=${state.sessionId}`;
      } catch (err) {
        console.error(err);
        showError("Something went wrong while saving your choices. Please try again.");
        btn.disabled = false;
        btn.textContent = "Next";
      }
    });
  }

  function renderProgressBar() {
    // Phase 4-A: 7-step flow (Step 0 + Steps 1..7). The customize page
    // is Step 2 — active here. Mirrors pages/_helpers.py::make_progress
    // so static HTML and Dash pages render identical progress bars.
    const steps = ["0. Welcome", "1. Role", "2. Customize", "3. Prices",
                   "4. Respond", "5. Compare", "6. Impacts", "7. Survey"];
    const ACTIVE = 2;
    const el = $("progress-bar");
    el.innerHTML = steps.map((label, i) => {
      const cls = i < ACTIVE ? "bg-success"
                : i === ACTIVE ? "bg-primary"
                : "bg-secondary";
      return `<span class="badge ${cls} me-1">${label}</span>`;
    }).join("");
  }

  // ---- Bootstrap ----
  document.addEventListener("DOMContentLoaded", () => {
    renderProgressBar();
    setupQuestionControls();
    setupButtons();
    loadInitial();
  });
})();
