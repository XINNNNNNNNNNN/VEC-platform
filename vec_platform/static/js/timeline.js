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
    // Phase N F6: floor area, drives the tiered grid fee (abonnemang)
    // in computeBillScenario so the live preview matches the backend.
    areaM2: null,
    // Phase O: building_type ('apartment' / 'townhouse' / 'house' /
    // 'other' / null) is accepted by computeBillScenario for caller
    // compatibility but no longer changes the bill (effekttariff
    // removed). Mirrors user_input.building_type.
    buildingType: null,
  };

  // ---- DOM helpers ----
  function $(id) { return document.getElementById(id); }

  function showError(msg) {
    const el = $("error-banner");
    el.textContent = msg;
    el.classList.remove("d-none");
  }

  // Phase O-fix-8: lightweight toast helper. Used by the calibration
  // PUT path to surface "out-of-range, snapped to default" feedback
  // when the backend clamps an input. Defaults to ~4s on screen with
  // a 200ms fade. No external dependencies — Bootstrap's toast
  // component isn't loaded on /step3.
  //
  //   showToast("EV daily charge must be 2–24 kWh. Reset to 8.");
  //   showToast("Saved", { kind: "info", ms: 1500 });
  function showToast(message, opts) {
    const container = $("vec-toast-container");
    if (!container) return;
    const kind = (opts && opts.kind) || "warn";   // info | warn | error
    const ms = (opts && opts.ms) || 4000;
    const el = document.createElement("div");
    el.className = `vec-toast vec-toast-${kind}`;
    el.textContent = message;
    container.appendChild(el);
    // Trigger CSS transition in next frame so .show animates in.
    requestAnimationFrame(() => el.classList.add("show"));
    setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.remove(), 250);
    }, ms);
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

    // Phase O-fix-2: BESS auto-managed placeholder REMOVED. BESS
    // charge / discharge windows are now rendered as two standard
    // draggable device blocks (bess_charge#1, bess_discharge#1) via
    // the same makeBlock + state.placed path as cooking / EV. The
    // priority dispatch (PV -> own_load -> BESS -> grid for charge;
    // BESS -> own_load -> grid for discharge) is applied at bill
    // computation time by VECCompute.applyBessDispatch (mirrors the
    // backend engine/mock.py _apply_bess_dispatch).

    // One row per placed device instance, in a stable order so the
    // visual doesn't jump. Order is base-type order × instance number.
    // v3.X-fix-5b: expand each base to up to MAX_INSTANCES_PER_BASE
    // rows so users can see / drag multiple cookings, dishwashers, etc.
    // Phase O-fix-4 Bug 1: use the module-level DEVICE_LIST_ORDER so
    // the timeline rows include bess_charge / bess_discharge (Phase
    // O-fix-2). The previous local ``order`` array was a stale copy
    // from before Phase O-fix-2 and missed both BESS keys, causing
    // BESS rows to disappear from the timeline even though they
    // appeared in the "My devices" list and the chart legend.
    for (const baseName of DEVICE_LIST_ORDER) {
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


  // ---- Phase O-fix-2: BESS overlap resolution ----
  // Two BESS windows (bess_charge#1 / bess_discharge#1) must not
  // overlap — a battery cannot charge and discharge simultaneously.
  // When the user releases a BESS block on top of the other window,
  // push the just-released block to the nearest non-overlapping
  // position. The "just-released" block is the active actor (the
  // user clearly intended that as the new position), so the OTHER
  // block stays put — we move the dragged one out of the way.
  function maybeResolveBessOverlap(droppedName) {
    if (droppedName !== "bess_charge#1" && droppedName !== "bess_discharge#1") {
      return;
    }
    const otherName = droppedName === "bess_charge#1"
      ? "bess_discharge#1"
      : "bess_charge#1";
    const dropped = state.placed[droppedName];
    const other = state.placed[otherName];
    if (!dropped || !other) return;  // single-block case, no conflict

    if (!rangesOverlap(dropped.start, dropped.duration, other.start, other.duration)) {
      return;
    }
    const newStart = findNearestNonOverlap(
      dropped.start, dropped.duration, other.start, other.duration,
    );
    if (newStart !== dropped.start) {
      dropped.start = newStart;
      // No toast library wired up — surface the auto-push via a
      // brief console note that pilot operators can inspect.
      console.info(
        `Phase O-fix-2: ${droppedName} auto-pushed to slot ${newStart} ` +
        `to avoid overlap with ${otherName} (${other.start}-${other.start + other.duration}).`
      );
    }
  }

  function rangesOverlap(s1, d1, s2, d2) {
    // Wrap-aware overlap check on a circular 0..SLOTS_PER_DAY domain.
    // Expand each range into a set of occupied slot indices and look
    // for intersection. 16 + 16 = 32 slots max — cheap.
    const set1 = new Set();
    for (let k = 0; k < d1; k++) set1.add((s1 + k) % SLOTS_PER_DAY);
    for (let k = 0; k < d2; k++) {
      if (set1.has((s2 + k) % SLOTS_PER_DAY)) return true;
    }
    return false;
  }

  function findNearestNonOverlap(droppedStart, droppedDur, otherStart, otherDur) {
    // Try increasing start (push later); fall back to decreasing
    // (push earlier); finally take the slot just past the other
    // window's end. Wrap-aware throughout.
    for (let delta = 1; delta <= SLOTS_PER_DAY; delta++) {
      const candidate = (droppedStart + delta) % SLOTS_PER_DAY;
      if (!rangesOverlap(candidate, droppedDur, otherStart, otherDur)) {
        return candidate;
      }
    }
    // Fallback: position the dropped block immediately after the
    // other window. With 96-slot day and 16-slot windows this is
    // always feasible (32 occupied << 96).
    return (otherStart + otherDur) % SLOTS_PER_DAY;
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
        // Phase 4-A-fix-4: real-time wrap rendering. While the user
        // drags across midnight, resize the held block to its tail
        // portion (start -> 24:00) and show a transient "head"
        // companion at slot 0..headDur so the wrap is visible during
        // the drag itself, not only on release. Single-segment drags
        // stay on the existing CSS-only path (no DOM thrash). The
        // companion is removed once the drag returns to non-wrap;
        // on pointerup, renderTimeline() rebuilds the row from
        // scratch and the transient companion is replaced by
        // makeBlock's permanent two-segment output.
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
        refreshChartAndBill();
      }
    });

    function endDrag(e) {
      if (!block.classList.contains("dragging")) return;
      block.classList.remove("dragging");
      try { block.releasePointerCapture(e.pointerId); } catch (_) {}
      // Phase O-fix-2: BESS overlap check. If the user just released
      // a BESS block on top of the other BESS window, push the
      // just-released block (the "later action") to the nearest
      // non-overlapping start. Both windows are 16 slots (4 h).
      maybeResolveBessOverlap(name);
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
      // Phase O-fix-6: refresh the "My devices" list so the time
      // string (XX:XX–YY:YY) reflects the new start_slot. Without
      // this, the list keeps showing the pre-drag time.
      renderDeviceList();
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
  // Phase O-fix-2: BESS schedule keys appended so the timeline /
  // device list iterate them via the same path as cooking / EV.
  // The makeBlock renderer reads load_kw + start + duration from
  // state.placed[name], identical to other devices.
  const DEVICE_LIST_ORDER = ["cooking", "dishwasher", "washing_machine",
                             "dryer", "oven_baking", "ev_charger",
                             "bess_charge", "bess_discharge"];

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

      // Phase O-fix-6: skip × button for nonRemovable devices (EV +
      // both BESS schedules). They are added / removed solely via
      // the Step 1 has_X toggle.
      if (!meta.nonRemovable) {
        const removeBtn = document.createElement("button");
        removeBtn.className = "device-remove-btn";
        removeBtn.type = "button";
        removeBtn.textContent = "×";
        removeBtn.title = `Remove ${friendly}`;
        removeBtn.addEventListener("click", () => removeDevice(name));
        li.appendChild(removeBtn);
      }

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
    // Phase O-fix-6: singleInstance types (EV + BESS charge/discharge)
    // are entirely hidden from the dropdown once placed — they cannot
    // be added a second time and the Step 1 toggle is the only way
    // to add/remove them.
    let addable = 0;
    for (const baseName of DEVICE_LIST_ORDER) {
      const meta = DEVICE_CATALOG[baseName];
      if (!meta || !meta.draggable) continue;
      // Phase O-fix-8: gate EV / BESS rows by the Step 1 has_X toggle.
      // Without this filter the dropdown surfaces "EV charger" /
      // "Battery charging" / "Battery discharging" options even for
      // participants who declared has_ev=False / has_bess=False on
      // Step 1, letting them bypass the survey gate and inflating
      // their bill with devices they don't own.
      if (baseName === "ev_charger" && !state.hasEv) continue;
      if (baseName === "bess_charge" && !state.hasBess) continue;
      if (baseName === "bess_discharge" && !state.hasBess) continue;
      const present = countInstancesOfBase(baseName, state.placed);
      if (meta.singleInstance && present >= 1) {
        // Skip — already placed, cannot add another, and surfacing it
        // disabled would just add visual noise.
        continue;
      }
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

    // Phase O-fix-2: apply BESS daily dispatch so the live preview
    // reflects the charge/discharge windows the user just dragged.
    // Mirrors the backend engine/mock.py _apply_bess_dispatch.
    const adjustedNet = VECCompute.applyBessDispatch(
      netLoad,
      state.pvGeneration,
      deviceArrays["bess_charge#1"],
      deviceArrays["bess_discharge#1"],
    );

    // Phase K-2 F4: pass the per-slot retail curve so live bill
    // updates while dragging a device reflect the actual cost at
    // each time-of-day, not a flat average.
    // Phase N F6: also pass areaM2 so grid_fee tier matches backend.
    // Phase O: pass buildingType (informational; effekttariff removed).
    const bill = VECCompute.computeBillScenario(
      adjustedNet, "no_vec", state.spotPrices, state.areaM2, state.buildingType
    );
    renderBillCard(bill);
  }

  function renderBillCard(bill) {
    // Phase M: customize is the configuration stage, not the
    // measurement stage. Showing a "vs. baseline" delta here
    // pre-anchors participant expectations before the Compare page
    // (Step 5) — the proper venue for 3-way scenario saving — runs
    // its willingness measurement. The Step-1-default baseline is
    // also not semantically meaningful (mixes calibration accuracy
    // with drag behaviour). Display absolute Net cost only.
    // state.originalBill is still maintained by loadInitial +
    // refetchBaselineAndRefresh (Phase L) in case downstream
    // analysis needs the calibration-aware anchor.
    const el = $("bill-card");

    function row(label, value) {
      return `<div class="bill-row"><span>${label}</span><span>${value.toLocaleString("en-US", { maximumFractionDigits: 0 })} SEK</span></div>`;
    }

    el.innerHTML = `
      ${row("Electricity purchase", bill.energy_purchase)}
      ${row("Grid fee", bill.grid_fee)}
      ${row("Energy tax", bill.energy_tax)}
      ${row("Feed-in income", -bill.feed_in_income)}
      <div class="bill-row total"><span>Net cost</span><span>${bill.net_cost.toLocaleString("en-US", { maximumFractionDigits: 0 })} SEK</span></div>
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
    // Phase N F6: pick up area_m2 so computeBillScenario uses the
    // same tiered grid fee as the backend. null is acceptable —
    // gridFeeFixed defaults to the lowest tier (100 SEK).
    state.areaM2 = profile.area_m2 ?? null;
    // Phase O: building_type informs the live-preview computeBillScenario
    // call (currently informational only; effekttariff removed).
    state.buildingType = profile.building_type ?? null;
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
      // Phase O-fix-6+: prefer the array value (session-correct,
      // server-rendered after cascade) over the catalog default
      // (a fresh-seed reference). Catalog load_kw was previously
      // winning via `??`, which broke variable-power devices
      // like bess_charge / bess_discharge whose array value
      // depends on bess_kwh (4C model). Static-power devices
      // (cooking, dishwasher, ev_charger) read identical values
      // from both sources, so this change is a no-op for them.
      const load_kw = (bounds && Number.isFinite(arr[bounds.start]) && arr[bounds.start] > 0)
        ? arr[bounds.start]
        : (catalogMeta.load_kw ?? 1.0);
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
    // Phase K-2 F4: pass the loaded retail curve so the baseline bill
    // uses the same per-slot pricing as the live preview.
    // Phase N F6: pass areaM2 so grid_fee matches backend tiered fee.
    // Phase O: pass buildingType (informational; effekttariff removed).
    state.originalBill = VECCompute.computeBillScenario(
      profile.net_load, "no_vec", state.spotPrices,
      state.areaM2, state.buildingType
    );

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
  // Phase O-fix-3: ev_kwh semantic changed from "EV battery capacity
  // (kWh, e.g. 60 Tesla Model 3)" to "daily charging energy in kWh
  // (e.g. 8 for ~40 km commute)". Default 8 (was 60).
  const _CAP_FIELDS = {
    pv:   { col: "pv_kwp",  default: 5  },
    bess: { col: "bess_kwh", default: 10 },
    ev:   { col: "ev_kwh",  default: 8  },
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
  // away.
  //
  // Phase O-fix-4 Bug 2: ALSO reseed state.placed for any device
  // whose shape changed via cascade (ev_charger duration scales with
  // ev_kwh; bess_charge / bess_discharge could change power; etc.).
  // The previous version refreshed baseLoad / pvGeneration but left
  // state.placed pointing at stale device arrays, so a user changing
  // ev_kwh from 8 to 20 in the Step 3 calibration panel saw the
  // backend bill update in the DB but the on-page bill card stayed
  // at the old number. Fine-grained merge: preserve the user's drag
  // start_slot (they may have moved a block before opening the
  // calibration panel), update duration + load_kw from the fresh
  // profile, drop any device no longer present.
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
    // Phase N F6: area_m2 cannot change via calibration, but refresh
    // it defensively in case the server response shape evolved.
    state.areaM2 = profile.area_m2 ?? state.areaM2;
    // Phase O: same defensive refresh for building_type.
    state.buildingType = profile.building_type ?? state.buildingType;

    // Phase O-fix-4: merge profile.devices into state.placed.
    // - For each device key in the fresh profile: keep the existing
    //   start (user's drag position) but adopt the new duration and
    //   load_kw (which the cascade may have changed).
    // - For each device key in state.placed that no longer exists in
    //   the fresh profile: drop it (the participant toggled the
    //   corresponding has_X off).
    if (profile.devices && typeof profile.devices === "object") {
      for (const [name, arr] of Object.entries(profile.devices)) {
        if (name === "base_load") continue;
        if (name.startsWith("__")) continue;  // metadata e.g. __scale_factor__
        if (!Array.isArray(arr)) continue;
        const catalogMeta = DEVICE_CATALOG[stripInstanceSuffix(name)];
        if (!catalogMeta) continue;
        const bounds = VECCompute.extractBounds(arr);
        if (!bounds) continue;  // empty array, can't derive shape
        const existing = state.placed[name];
        const start = existing && existing.start != null
          ? existing.start          // preserve user's drag
          : bounds.start;           // first seed
        // Phase O-fix-6+: prefer the cascade-rewritten array value
        // (session-correct) over the catalog default. The previous
        // `??` precedence ignored the array for any device whose
        // catalog defined load_kw — that includes the variable-power
        // bess_charge / bess_discharge (catalog 2.5 kW seed vs
        // array 5.0 kW after bess_kwh=20 calibration), which made
        // the on-page bill refuse to update.
        const load_kw = (Number.isFinite(arr[bounds.start]) && arr[bounds.start] > 0)
          ? arr[bounds.start]
          : (catalogMeta.load_kw ?? 1.0);
        state.placed[name] = {
          start,
          duration: bounds.duration,
          load_kw,
        };
      }
      // Drop devices that no longer exist on the server (e.g. user
      // unchecked has_bess in Step 1 — though that path normally
      // cascades through a different code path; this is defensive).
      for (const name of Object.keys(state.placed)) {
        if (!(name in profile.devices)) {
          delete state.placed[name];
        }
      }
    }

    // Phase L: re-anchor the "vs. baseline" delta on the calibrated
    // state. Without this, dragging a device after raising PV from 5
    // to 15 would show a saving that includes the calibration delta
    // (≈1267 SEK) on top of the drag-induced saving — contaminating
    // Layer 1/2/3 research signals that need to isolate behavioural
    // response from one-time setup accuracy. The fresh profile here
    // is the post-cascade step=2 row (Phase K-2 fix-1), so its
    // net_load already reflects current calibration.
    // Phase N F6: pass areaM2 for tiered grid_fee consistency.
    // Phase O: pass buildingType (informational; effekttariff removed).
    state.originalBill = VECCompute.computeBillScenario(
      profile.net_load, "no_vec", state.spotPrices,
      state.areaM2, state.buildingType
    );
    // Phase O-fix-4: re-render timeline + device list so the new
    // duration / load_kw appear visually, in addition to refreshing
    // the chart + bill.
    renderTimeline();
    renderDeviceList();
    renderAddSelect();
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
    // Phase O-fix-8: send the RAW user value (even 0 or out-of-range)
    // so the backend's _validate_and_correct can detect it and reply
    // with a `corrected` entry. The previous logic silently rewrote
    // `0` → meta.default on the client, which made the backend see a
    // valid value, skip correction, and return no toast — leaving
    // the DOM input box stuck at 0 while the DB and bill silently
    // used the default. The only client-side coercion still needed
    // is NaN protection (e.g. blank input box → empty string →
    // NaN); a blank field falls back to the default so the PUT
    // payload remains numeric.
    const value = Number.isFinite(raw) ? raw : meta.default;
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

  // Phase O-fix-8: reverse-lookup tables for the calibration PUT
  // response. Backend returns `corrected: {bess_kwh: 10, ev_kwh: 8}`
  // when a value is out of range; we need to (a) find the matching
  // DOM input by id-prefix to overwrite the user's bogus number, and
  // (b) build a human label for the toast.
  const _COL_TO_PREFIX = { pv_kwp: "pv", bess_kwh: "bess", ev_kwh: "ev" };
  // Phase O-fix-9: pv_kwp now has a real range ("1–25") so the toast
  // template fires instead of falling back to "was out of range". The
  // label "PV size" matches the step3 hint copy ("Range 1–25 kW.
  // Typical 5 kW") so participants see consistent wording.
  const _COL_TO_LABEL = {
    pv_kwp:   { name: "PV size",          unit: "kW",       range: "1–25" },
    bess_kwh: { name: "Battery capacity", unit: "kWh",      range: "2–50" },
    ev_kwh:   { name: "EV daily charge",  unit: "kWh/day",  range: "2–24" },
  };

  async function persistCalibration() {
    if (!state.sessionId) return;
    const patch = _calibrationPatchPending;
    _calibrationPatchPending = {};
    _calibrationTimer = null;
    if (Object.keys(patch).length === 0) return;
    const body = { session_id: state.sessionId, ...patch };
    let ok = false;
    let corrected = null;
    try {
      const r = await fetch("/api/user_input/calibration", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      ok = r.ok;
      if (r.ok) {
        // Phase O-fix-8: read the corrected dict so the UI can
        // resync. JSON parse may throw on a server that returns
        // empty body — swallow defensively.
        try {
          const data = await r.json();
          corrected = (data && data.corrected) || null;
        } catch (_) {
          corrected = null;
        }
      } else {
        const detail = await r.text().catch(() => "");
        console.warn("Calibration persist failed:", r.status, detail);
      }
    } catch (e) {
      console.warn("Calibration persist error:", e);
    }
    // Phase O-fix-8: apply backend's auto-correct to the DOM input
    // box + show a toast. Without this the user keeps seeing "0" or
    // "100" in the input even though the bill reflects the engine
    // fallback default, which looks like a broken interaction.
    if (corrected) {
      for (const [col, defaultValue] of Object.entries(corrected)) {
        const prefix = _COL_TO_PREFIX[col];
        if (!prefix) continue;
        const inp = document.getElementById(`${prefix}-capacity-input`);
        if (inp) inp.value = defaultValue;
        const lbl = _COL_TO_LABEL[col] || { name: col, unit: "", range: "" };
        const msg = lbl.range
          ? `${lbl.name} must be ${lbl.range} ${lbl.unit}. Reset to ${defaultValue}.`
          : `${lbl.name} was out of range. Reset to ${defaultValue}.`;
        showToast(msg, { kind: "warn", ms: 4000 });
      }
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

  // Phase J: BFCache restore. When the user presses Back from /dash/step3
  // (prices page) the browser may serve /step3 from BFCache, which
  // preserves the DOM verbatim including the transient "Saving…" +
  // disabled state that the Next click handler set just before
  // navigating away. DOMContentLoaded does NOT fire on BFCache restore,
  // so the bootstrap above never re-runs and the button stays stuck.
  //
  // Reset only the transient submit-cycle UI here: button label back to
  // its HTML default and the error banner cleared. We deliberately do
  // NOT force btn.disabled=false — the confidence-radio change handler
  // (setupQuestionControls) already drives that based on whether the
  // confidence Likert has been answered, and BFCache preserves the
  // radio's checked state, so the disable-toggle will fire correctly
  // on the participant's next interaction. Forcing enabled here would
  // let an empty form be submitted.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    const btn = document.getElementById("btn-confirm");
    if (btn) btn.textContent = "Next";
    const err = document.getElementById("step3-error");
    if (err) err.textContent = "";
    // Phase J-fix-1: dispatch a synthetic change event on the
    // currently-checked confidence radio so the existing change
    // handler re-runs btn.disabled = false. Chromium does NOT fire
    // 'change' when the user clicks a radio that is already checked,
    // so without this BFCache participants would see "Next" but the
    // button would stay disabled until they actively switched radios.
    // If nothing is checked the synthetic dispatch is skipped and
    // the button correctly stays disabled until the participant
    // makes a real selection.
    const checkedConfidence = document.querySelector(
      'input[name="step3-confidence"]:checked'
    );
    if (checkedConfidence) {
      checkedConfidence.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
})();
