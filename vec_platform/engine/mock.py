"""Mock calculation engine with fake data for development."""

import json

from vec_platform.engine.base import CalculationEngine
from vec_platform.models import UserInput, DailyProfile, BillBreakdown, ShadowPrices
from vec_platform.config import (
    ENERGY_TAX,
    VEC_INTERNAL_BUY,
    VEC_INTERNAL_SELL,
    FEED_IN_PRICE,
    GRID_FEE_VARIABLE_RATE,
    grid_fee_fixed,
    APARTMENT_BUILDINGS,
    BESS_POWER_KW,
    BESS_DURATION_SLOTS,
    BESS_CHARGE_KWH_PER_DAY,
    BESS_DISCHARGE_KWH_PER_DAY,
    BESS_CHARGE_DEFAULT_START,
    BESS_DISCHARGE_DEFAULT_START,
    SLOTS_PER_DAY,
)


# Phase O-fix-2: device keys carrying the BESS schedule. They live in
# profile.devices alongside cooking#1 / dishwasher#1 / etc. so the JS
# timeline can render them as draggable blocks via the same code path.
# They are NOT summed into flexible_load — energy storage redirects
# flow rather than consuming it, so the priority dispatch in
# calculate_bill handles their effect explicitly.
BESS_DEVICE_KEYS = ("bess_charge#1", "bess_discharge#1")
# Phase N F9: RETAIL_PRICE_BASE and GRID_FEE_MONTHLY are deprecated
# (replaced by _SE3_SUMMER_RETAIL_SEK_PER_KWH per-slot curve and the
# tiered grid_fee_fixed + GRID_FEE_VARIABLE_RATE respectively). Both
# are intentionally NOT imported above so a stale code path that
# tries to use them fails at import time, not silently.
#
# Phase O: EFFEKTTARIFF_* constants and the per-kW peak fee are no
# longer imported either — Sweden's 2026 mandate was cancelled and
# the engine no longer adds the peak component to grid_fee.

DAYS_PER_MONTH = 30


# v3.6: hardcoded representative SE3 summer day with strong PV surplus
# at midday. 96 slots (15-min granularity). SEK/kWh, includes grid fee
# and energy tax (consumer-facing retail price).
#
# Shape rationale:
#   00:00-06:00 (slots 0-23):    low demand,   ~0.30 SEK/kWh
#   06:00-09:00 (slots 24-35):   morning peak, ~0.85
#   09:00-11:00 (slots 36-43):   PV ramping,   ~0.40 declining
#   11:00-14:00 (slots 44-55):   PV surplus,   ~0.05-0.10 (trough)
#   14:00-17:00 (slots 56-67):   PV decline,   ~0.45
#   17:00-21:00 (slots 68-83):   evening peak, ~0.95
#   21:00-24:00 (slots 84-95):   wind-down,    ~0.50
#
# Placeholder values for development. Replace with real Nord Pool CSV
# before pilot launch. Keep this list at exactly 96 floats.
_SE3_SUMMER_RETAIL_SEK_PER_KWH = [
    # 00:00 - 06:00 (24 slots): low demand
    0.32, 0.30, 0.29, 0.28, 0.27, 0.27, 0.27, 0.28,  # 0-2h
    0.28, 0.29, 0.29, 0.30, 0.31, 0.32, 0.33, 0.35,  # 2-4h
    0.38, 0.42, 0.46, 0.51, 0.55, 0.60, 0.66, 0.74,  # 4-6h
    # 06:00 - 09:00 (12 slots): morning peak
    0.82, 0.86, 0.88, 0.89, 0.90, 0.91, 0.91, 0.90,  # 6-8h
    0.88, 0.84, 0.78, 0.70,                           # 8-9h
    # 09:00 - 11:00 (8 slots): PV ramping
    0.62, 0.55, 0.48, 0.42, 0.36, 0.30, 0.24, 0.18,  # 9-11h
    # 11:00 - 14:00 (12 slots): PV surplus trough
    0.13, 0.09, 0.06, 0.05, 0.05, 0.06, 0.07, 0.08,  # 11-13h
    0.10, 0.13, 0.17, 0.22,                           # 13-14h
    # 14:00 - 17:00 (12 slots): PV declining
    0.28, 0.34, 0.39, 0.42, 0.45, 0.47, 0.49, 0.52,  # 14-16h
    0.56, 0.62, 0.69, 0.78,                           # 16-17h
    # 17:00 - 21:00 (16 slots): evening peak
    0.86, 0.92, 0.96, 0.98, 0.99, 1.00, 0.99, 0.97,  # 17-19h
    0.95, 0.93, 0.89, 0.85, 0.79, 0.72, 0.65, 0.58,  # 19-21h
    # 21:00 - 24:00 (12 slots): wind-down
    0.52, 0.48, 0.45, 0.43, 0.41, 0.39, 0.38, 0.36,  # 21-23h
    0.34, 0.33, 0.32, 0.31,                           # 23-24h
]
assert len(_SE3_SUMMER_RETAIL_SEK_PER_KWH) == 96, (
    f"SE3 hardcoded curve must have 96 slots, "
    f"got {len(_SE3_SUMMER_RETAIL_SEK_PER_KWH)}"
)

# Mechanical derivations from retail (no time-of-day variation).
_VEC_INTERNAL_BUY_DISCOUNT = 0.85   # internal_buy = retail × 0.85
_VEC_INTERNAL_SELL_PRICE   = 1.05   # SEK/kWh, flat
# Phase N F7: kept in sync with config.FEED_IN_PRICE (0.40). This
# local copy is what get_shadow_prices emits to the UI; if it drifts
# from config the customize/respond pages would see different numbers
# from what calculate_bill uses.
_FEED_IN_PRICE             = 0.55   # SEK/kWh, flat (matches config.FEED_IN_PRICE; Phase O post-skattereduktion)


class MockEngine(CalculationEngine):
    """Mock engine with fake data for development."""

    def generate_profile(self, user_input: UserInput) -> DailyProfile:
        """Generate mock 96-slot load profile with per-device breakdown."""

        devices = self._get_devices(user_input)
        base_load = devices["base_load"]
        # Phase O-fix-2: BESS schedule entries (bess_charge#1 /
        # bess_discharge#1) are stored alongside other devices so the
        # timeline can render them as draggable blocks, but they are
        # NOT summed into flexible_load. Storage redirects energy
        # flow rather than consuming it; the priority dispatch in
        # calculate_bill handles their effect on grid import/export.
        flexible_load = [
            sum(
                devices[name][i]
                for name in devices
                if name != "base_load" and name not in BESS_DEVICE_KEYS
            )
            for i in range(SLOTS_PER_DAY)
        ]
        pv_generation = self._get_pv_generation(user_input)
        net_load = [
            base_load[i] + flexible_load[i] - pv_generation[i]
            for i in range(SLOTS_PER_DAY)
        ]

        return DailyProfile(
            session_id=user_input.session_id,
            step=2,
            rigid_load=json.dumps(base_load),
            flexible_load=json.dumps(flexible_load),
            pv_generation=json.dumps(pv_generation),
            net_load=json.dumps(net_load),
            devices=json.dumps(devices),
        )

    def calculate_bill(
        self,
        profile: DailyProfile,
        scenario: str,
        area_m2: float | None = None,
        building_type: str | None = None,
        ownership_type: str | None = None,
    ) -> BillBreakdown:
        """Calculate a monthly bill breakdown for one scenario.

        Phase K-2 F4: replaced flat ``RETAIL_PRICE_BASE`` with a per-slot
        integral against the SE3 summer retail curve. Users dragging a
        device from the 17-21 evening peak (~1.0 SEK/kWh) into the
        11-14 PV-surplus trough (~0.05 SEK/kWh) now see a real,
        physically-meaningful bill reduction instead of a flat 1.5
        SEK/kWh that ignored when they ran.

        Phase K-2 F5: pv_self_consumption is informational only. The
        ``net_load`` curve consumed below is already net of PV
        generation (computed in generate_profile as
        base + flexible - pv), so ``energy_purchase`` only charges for
        electricity actually pulled from the grid — PV self-consumption
        is implicit in that already-reduced figure. The
        ``pv_self_consumption`` field is therefore presented to the UI
        as the value of self-consumed PV (avoided purchase) but
        deliberately NOT subtracted again from net_cost; doing so
        would double-count.
        """

        net_load = json.loads(profile.net_load) if isinstance(profile.net_load, str) else profile.net_load
        pv_gen = json.loads(profile.pv_generation) if isinstance(profile.pv_generation, str) else profile.pv_generation

        SLOT_HOURS = 0.25  # 15 minutes

        # Phase O-fix-2: apply BESS dispatch on top of the pre-BESS
        # net_load. Returns a new per-slot net_load that reflects the
        # priority logic (PV -> own_load -> BESS -> grid for charge;
        # BESS -> own_load -> grid for discharge). If no BESS schedule
        # is present (has_bess=False or no schedule slot), returns
        # net_load unchanged.
        net_load = self._apply_bess_dispatch(profile, net_load, pv_gen)

        # ---- Per-slot integration against the time-varying retail curve ----
        # Phase K-2 F4. Only positive net_load (= electricity bought from
        # the grid) contributes to ``energy_purchase``; negative net_load
        # is export and feeds into ``feed_in_income`` further down.
        daily_purchase_sek = sum(
            max(0.0, net_load[i]) * SLOT_HOURS * _SE3_SUMMER_RETAIL_SEK_PER_KWH[i]
            for i in range(SLOTS_PER_DAY)
        )
        consumed_daily = sum(max(0.0, x) for x in net_load) * SLOT_HOURS
        exported_daily = sum(max(0.0, -x) for x in net_load) * SLOT_HOURS

        consumed_monthly = consumed_daily * DAYS_PER_MONTH
        exported_monthly = exported_daily * DAYS_PER_MONTH

        energy_purchase = daily_purchase_sek * DAYS_PER_MONTH
        # Phase N F6: structured grid fee = abonnemang (fixed by main
        # breaker ampere via area proxy) + rörlig elöverföring (per
        # kWh transmitted). Replaces flat 580 SEK that previously
        # over-charged apartments and under-charged large villas.
        grid_fee = (
            grid_fee_fixed(area_m2)
            + consumed_monthly * GRID_FEE_VARIABLE_RATE
        )
        # Phase O: effekttariff REMOVED. The Swedish 2026 DSO mandate
        # was cancelled 2026-03-13 and the major SE3 utilities have
        # withdrawn or paused their roll-outs. ``ownership_type`` and
        # ``building_type`` are accepted by the signature for caller
        # compatibility but no longer influence grid_fee.
        _ = (ownership_type, building_type)  # kept for stable signature
        tax = consumed_monthly * ENERGY_TAX

        # ---- PV self-consumption value (informational, F5) ----
        # Per-slot: how many kW of PV generation is actually offsetting
        # this slot's own demand vs. flowing out as export?
        # total_load[i] = pv_gen[i] + net_load[i]   (engine invariant)
        # pv_self[i] = min(pv_gen[i], total_load[i]) = min(pv_gen[i], pv_gen[i] + net_load[i])
        #            = pv_gen[i] if net_load[i] >= 0 (load >= PV → all PV self-consumed)
        #            = pv_gen[i] + net_load[i] if net_load[i] < 0 (export → some PV self, some out)
        daily_pv_self_sek = sum(
            min(pv_gen[i], max(0.0, pv_gen[i] + net_load[i]))
            * SLOT_HOURS
            * _SE3_SUMMER_RETAIL_SEK_PER_KWH[i]
            for i in range(SLOTS_PER_DAY)
        )
        pv_self_consumption = daily_pv_self_sek * DAYS_PER_MONTH

        if scenario == "no_vec":
            vec_discount = 0.0
            feed_in_income = exported_monthly * FEED_IN_PRICE
        elif scenario == "vec_no_adjust":
            vec_discount = consumed_monthly * 0.15
            feed_in_income = exported_monthly * VEC_INTERNAL_SELL
        else:  # vec_adjusted
            vec_discount = consumed_monthly * 0.25
            feed_in_income = exported_monthly * VEC_INTERNAL_SELL

        # F5 strategy A: pv_self_consumption is NOT subtracted (would
        # double-count — see method docstring).
        net_cost = (
            energy_purchase + grid_fee + tax
            - vec_discount - feed_in_income
        )

        return BillBreakdown(
            session_id=profile.session_id,
            scenario=scenario,
            step=profile.step,
            energy_purchase=round(energy_purchase, 2),
            grid_fee=round(grid_fee, 2),
            energy_tax=round(tax, 2),
            pv_self_consumption=round(pv_self_consumption, 2),
            vec_discount=round(vec_discount, 2),
            feed_in_income=round(feed_in_income, 2),
            net_cost=round(net_cost, 2),
        )

    @staticmethod
    def _bess_window_from_array(arr) -> int | None:
        """Return the start slot of a BESS schedule array, or None.

        BESS devices live in ``profile.devices`` as 96-slot arrays with
        BESS_POWER_KW in BESS_DURATION_SLOTS slots and 0 elsewhere.
        Returns the index of the first non-zero slot so the dispatch
        loop can re-derive the window without depending on a separate
        column. Returns None if the array is empty / all-zero (no BESS
        scheduled).
        """
        if not isinstance(arr, list) or not arr:
            return None
        for i, v in enumerate(arr):
            if v > 0:
                return i
        return None

    def _apply_bess_dispatch(self, profile, net_load, pv_gen):
        """Phase O-fix-2: adjust net_load per BESS schedule.

        Reads bess_charge#1 and bess_discharge#1 from profile.devices
        (each a 96-slot array, BESS_POWER_KW in the window, 0 outside),
        then applies the priority logic per slot:

          charge slot  : own_load gets PV first; remaining PV up to
                         charge_per_slot goes to BESS; grid backfills
                         to charge_per_slot.
          discharge slot: BESS supplies own_load up to whatever load
                         remains after PV; surplus BESS energy exports
                         to grid.

        Effect on net_load:
          - grid -> BESS (charge slot): net_load[i] += grid_to_bess
          - PV -> BESS  (charge slot): net_load[i] += pv_to_bess
                          (PV that would have exported now stays in)
          - BESS -> own_load (discharge): net_load[i] -= bess_to_load
                          (load satisfied without grid import)
          - BESS -> grid   (discharge): net_load[i] -= bess_to_grid
                          (additional export)

        Daily energy: 10 kWh charge -> 9 kWh discharge (round-trip 0.9).
        bess_kwh capacity is NOT consulted in this phase; the cycle is
        fixed regardless of user-configured battery size.
        """
        devices_raw = getattr(profile, "devices", None)
        if not devices_raw:
            return net_load
        try:
            devices = (
                json.loads(devices_raw)
                if isinstance(devices_raw, str)
                else devices_raw
            )
        except (TypeError, ValueError):
            return net_load

        charge_arr = devices.get("bess_charge#1")
        discharge_arr = devices.get("bess_discharge#1")
        charge_start = self._bess_window_from_array(charge_arr)
        discharge_start = self._bess_window_from_array(discharge_arr)
        if charge_start is None and discharge_start is None:
            return net_load

        SLOT_HOURS = 0.25
        charge_per_slot_kwh = BESS_CHARGE_KWH_PER_DAY / BESS_DURATION_SLOTS
        discharge_per_slot_kwh = BESS_DISCHARGE_KWH_PER_DAY / BESS_DURATION_SLOTS

        # Reconstruct own_load (pre-PV demand) per slot to drive the
        # priority decisions. net_load = own_load - pv, so:
        own_load = [net_load[i] + pv_gen[i] for i in range(SLOTS_PER_DAY)]

        adjusted = list(net_load)

        # ---- Charge window ----
        if charge_start is not None:
            for k in range(BESS_DURATION_SLOTS):
                i = (charge_start + k) % SLOTS_PER_DAY
                # Energy this slot in kWh.
                pv_kwh = max(0.0, pv_gen[i]) * SLOT_HOURS
                load_kwh = max(0.0, own_load[i]) * SLOT_HOURS
                # Priority 1: PV serves own_load.
                pv_used_for_load = min(pv_kwh, load_kwh)
                pv_remaining = pv_kwh - pv_used_for_load
                # Priority 2: PV surplus tops up BESS.
                pv_to_bess = min(pv_remaining, charge_per_slot_kwh)
                # Priority 3: grid backfills BESS to the per-slot target.
                grid_to_bess = max(0.0, charge_per_slot_kwh - pv_to_bess)
                # net_load is in kW (energy / 0.25h).
                # PV captured by BESS would otherwise have exported: net_load
                # becomes less negative -> add pv_to_bess / SLOT_HOURS.
                adjusted[i] += (pv_to_bess + grid_to_bess) / SLOT_HOURS

        # ---- Discharge window ----
        if discharge_start is not None:
            for k in range(BESS_DURATION_SLOTS):
                i = (discharge_start + k) % SLOTS_PER_DAY
                pv_kwh = max(0.0, pv_gen[i]) * SLOT_HOURS
                load_kwh = max(0.0, own_load[i]) * SLOT_HOURS
                # Remaining own_load after PV has been applied.
                load_after_pv = max(0.0, load_kwh - pv_kwh)
                # Priority 1: BESS supplies own_load (cap at per-slot rate).
                bess_to_load = min(discharge_per_slot_kwh, load_after_pv)
                # Priority 2: BESS surplus exports to grid.
                bess_to_grid = max(0.0, discharge_per_slot_kwh - bess_to_load)
                adjusted[i] -= (bess_to_load + bess_to_grid) / SLOT_HOURS

        return adjusted

    def get_shadow_prices(self, session_id: str) -> ShadowPrices:
        """Return per-slot prices for Step 4/5 visualisation.

        v3.6: retail comes from the hardcoded SE3 summer curve
        (representative PV-surplus day). Internal pricing is mechanically
        derived: internal_buy = retail × 0.85, sell/feed_in are flat.

        Returns a ``ShadowPrices`` ORM row (caller does ``db.add(row)``);
        the return shape was kept as the ORM model, not a plain dict, so
        existing callers in api/shadow_price.py and pages/step3.py
        (the prices page, renamed step4 → step3 in Phase 4-A) keep
        working unchanged.
        """
        retail = list(_SE3_SUMMER_RETAIL_SEK_PER_KWH)
        internal_buy = [round(p * _VEC_INTERNAL_BUY_DISCOUNT, 4) for p in retail]
        internal_sell = [_VEC_INTERNAL_SELL_PRICE] * SLOTS_PER_DAY
        feed_in = [_FEED_IN_PRICE] * SLOTS_PER_DAY

        return ShadowPrices(
            session_id=session_id,
            retail_price=json.dumps(retail),
            internal_buy=json.dumps(internal_buy),
            internal_sell=json.dumps(internal_sell),
            feed_in_price=json.dumps(feed_in),
        )

    # -------- Internal helpers --------

    def _get_base_load(
        self,
        building_type: str,
        area_m2: float | None = None,
        people: int | None = None,
    ) -> list:
        """Rigid baseline: fridge/lighting/standby + morning & evening peaks.

        Spec (archetype defaults, sized for 75 m² / 2 people):
          apartment: base 0.15 kW, peak 0.6 kW (06-09, 17-22)
            — Phase N-fix-2: halved from (0.3, 1.2). Sweden's 90%+
              apartments use district heating; electricity covers
              lighting + appliances only. Pre-fix value implicitly
              included an electric-heating component that doesn't
              exist for renters, producing ~277 kWh/month for a
              50 m² studio (real summer typical: 100-200).
          villa_pv / villa_pvbess: base 0.3 kW, peak 1.0 kW
          villa_noder: base 0.3 kW, peak 0.9 kW
            — Phase N-fix-4: halved from (0.5, 1.8) and (0.5, 1.5)
              respectively. Modern Swedish villas increasingly use
              heat pumps (COP 3-4) or district heating, leaving the
              raw electric load to lighting + appliances + summer
              cooking. The pre-fix archetype implicitly modelled
              resistive electric heat which is now a small minority
              of the stock. K-1 R3 (heating-type split as a Step 1
              option) remains the proper structural fix; halving is
              the safer default until that lands.

        Phase K-2 F2: scale by area_m2 and people. Pre-K-2 these two
        Step 1 inputs were collected but had zero effect on the engine
        — a 50 m² studio and a 200 m² villa with the same archetype
        produced identical bills. Now:

          area_scale = (area_m2 / 75) ** 0.7    # sublinear, larger
                                                # homes don't scale 1:1
                                                # with floor area
          people_scale = 0.7 + 0.15 * people    # 2 ppl → 1.0; 5 ppl → 1.45

        Both factors multiply the archetype base & peak. 75 m² + 2 ppl
        reproduces the pre-K-2 numbers exactly so existing pilot data
        stays comparable.
        """
        if building_type == "apartment":
            # Phase N-fix-2: district-heated apartments (Swedish norm),
            # not electric-heated. See docstring above.
            base, peak = 0.15, 0.6
        elif building_type == "villa_noder":
            # Phase N-fix-4: halved from (0.5, 1.5).
            base, peak = 0.3, 0.9
        else:  # villa_pv, villa_pvbess
            # Phase N-fix-4: halved from (0.5, 1.8).
            base, peak = 0.3, 1.0

        # Phase K-2 F2 scaling. Defensive defaults preserve archetype
        # behaviour when called without user_input (e.g. unit tests).
        if area_m2 is None:
            area_m2 = 75.0
        if people is None:
            people = 2
        area_scale = (max(20.0, float(area_m2)) / 75.0) ** 0.7
        people_scale = 0.7 + 0.15 * max(1, int(people))
        scale = area_scale * people_scale
        base *= scale
        peak *= scale

        load = [base] * SLOTS_PER_DAY
        for i in range(SLOTS_PER_DAY):
            hour = i * 15 // 60
            if 6 <= hour < 9 or 17 <= hour < 22:
                load[i] = peak
        return load

    def _get_devices(self, user_input: UserInput) -> dict:
        """Per-device 96-slot load arrays (kW).

        Phase 3.7-pre catalog (matches static/js/devices.js DEVICE_CATALOG):
          cooking         — single dinner-time block (was cooking_am+cooking_pm)
          dishwasher      — evening
          washing_machine — evening, 2.0 kW (was 0.5 kW)
          ev_charger      — only if user_input.has_ev
        Tumble dryer and oven_baking are NOT in the baseline; they only
        appear if the user adds them on the Step 3 page.

        v3.X-fix-5a: instance keys are now suffixed with ``#1`` so the
        rest of the pipeline can disambiguate a second/third instance of
        the same device type (added later via Step 3 in fix-5b/c). The
        suffix is the canonical key used in ``daily_profiles.devices``
        and ``device_shifts.device_name``. ``base_load`` keeps its bare
        name — it is the rigid background, not a device instance.
        """
        building_type = self._derive_building_type(user_input)
        # Phase K-2 F2: forward area_m2 + people so the base load
        # actually depends on the participant's household size.
        # Phase N-fix-3: flex devices (cooking / dishwasher / washing)
        # scale by household size via duration adjustment. Default
        # durations are sized for the 2-person baseline; 1-person
        # households cook smaller portions and run wet appliances less
        # often, 5-person households the opposite. Sub-linear (0.8 /
        # 1.0 / 1.6 etc.) reflects that fixed device capacity caps how
        # much more a 5-person home actually runs vs a 2-person home.
        # EV charging is intentionally NOT scaled — one EV draws the
        # same charge regardless of household size.
        people = getattr(user_input, "people", None) or 2
        flex_scale = 0.6 + 0.2 * max(1, int(people))
        # Phase O: N-fix-5 single-tenant guard REMOVED. Step 1 no
        # longer asks ownership_type, so the engine cannot identify
        # the "single 50 m² renter" sub-segment that motivated the
        # dishwasher-skip and washing-duration-halving. All flex
        # devices revert to the standard catalog, with N-fix-3 (flex
        # duration scaling by people) still active for everyone.

        def _scaled_block(start, end, kw):
            dur = end - start
            new_dur = max(1, round(dur * flex_scale))
            return self._device_block(start, start + new_dur, kw)

        devices: dict[str, list[float]] = {
            "base_load": self._get_base_load(
                building_type,
                area_m2=getattr(user_input, "area_m2", None),
                people=people,
            ),
            # Cooking — dinner only (Phase 3.7-pre collapsed AM+PM into one).
            "cooking#1": _scaled_block(72, 76, 2.0),       # 18:00-19:00 base, 2 kW
            "dishwasher#1": _scaled_block(78, 84, 1.2),    # 19:30-21:00 base, 1.2 kW
            "washing_machine#1": _scaled_block(76, 84, 2.0),  # 19:00-21:00 base, 2.0 kW
        }

        # v3 dropped the heating question along with the water_heater device.

        # EV charging overnight (22:00-01:30, 3.5h, wraps midnight).
        # Phase N-fix-3: NOT flex-scaled (single vehicle, not per-person).
        # Phase O-fix-1: calibrated to Swedish villa+EV household reality.
        # Power 2.3 kW = Schuko 10A nödladdning (Elsäkerhetsverket standard,
        # most prevalent before wallbox installation); duration 14 slots
        # (3.5h) × 2.3 kW × 0.25h = 8.05 kWh/day = 241 kWh/month.
        # Targets ~1450 mil/year (between Trafikanalys vanlig bilägare
        # 1500 mil/year and Vattenfall E-mobility national EV average
        # 1200 mil/year), 2 kWh/mil consensus. The previous N-fix-4
        # default (4h × 3.7 kW = 14.8 kWh/day) overstated by 85 %.
        # Default-start at 22:00 puts the block in the cheap night
        # window — the SP experiment measures whether users keep it
        # there or drag it into peak hours.
        if user_input.has_ev:
            devices["ev_charger#1"] = self._device_block(88, 88 + 14, 2.3)

        # Phase O-fix-2: BESS charge + discharge windows. Stored as
        # 96-slot arrays of 2.5 kW (BESS_POWER_KW) so the timeline
        # renders them as standard draggable blocks. They are
        # intentionally NOT summed into flexible_load by
        # generate_profile — energy storage redirects flow rather than
        # consuming it, so the priority dispatch in calculate_bill
        # handles the bill effect explicitly.
        if user_input.has_bess:
            devices["bess_charge#1"] = self._device_block(
                BESS_CHARGE_DEFAULT_START,
                BESS_CHARGE_DEFAULT_START + BESS_DURATION_SLOTS,
                BESS_POWER_KW,
            )
            devices["bess_discharge#1"] = self._device_block(
                BESS_DISCHARGE_DEFAULT_START,
                BESS_DISCHARGE_DEFAULT_START + BESS_DURATION_SLOTS,
                BESS_POWER_KW,
            )

        return devices

    @staticmethod
    def _derive_building_type(user_input: UserInput) -> str:
        """Map Phase O building_type → engine archetype code.

        Internal helper only; the engine still uses 4 archetype codes
        for backward-compat with _get_base_load (apartment /
        villa_noder / villa_pv / villa_pvbess). Phase O collapses to
        two distinct base/peak tuples but keeps the sub-codes so
        DER-presence still toggles the small villa_pv vs villa_pvbess
        vs villa_noder split.

        Phase O mapping:
          building_type == 'apartment'    -> 'apartment'
          building_type IN {townhouse,
                            house,
                            other,
                            NULL}         -> villa_noder / villa_pv / villa_pvbess
                                             (sub-selected by DER)

        ``ownership_type`` is no longer consulted (deprecated column).
        Legacy 'tenant' rows would have mapped to apartment; with the
        column relaxed to nullable in Phase O, only building_type
        matters going forward.
        """
        building_type = getattr(user_input, "building_type", None)
        if building_type in APARTMENT_BUILDINGS:
            return "apartment"
        # All other values (townhouse, house, other, NULL) share the
        # house archetype. DER-driven sub-codes preserved so the
        # existing N-fix-4 tuples (villa_pv 0.3/1.0, villa_noder
        # 0.3/0.9) continue to apply.
        if user_input.has_pv and user_input.has_bess:
            return "villa_pvbess"
        if user_input.has_pv:
            return "villa_pv"
        return "villa_noder"

    @staticmethod
    def _device_block(start_slot: int, end_slot: int, kw: float) -> list:
        """Create a 96-slot array with `kw` between start_slot (inclusive) and end_slot (exclusive).

        Phase O-fix-1: wrap-aware. When end_slot > SLOTS_PER_DAY (e.g. a
        device that starts at 22:00 and runs 3.5h ends at 01:30 = slot
        102), the loop wraps around the day boundary so the trailing
        slots populate at the start of the array. Mirrors the wrap
        logic already in api/profile.py /recalculate (Phase 3.X-fix-18)
        and the timeline.js / step5.js block renderer.
        """
        arr = [0.0] * SLOTS_PER_DAY
        for i in range(start_slot, end_slot):
            arr[i % SLOTS_PER_DAY] = kw
        return arr

    def _get_pv_generation(self, user_input: UserInput) -> list:
        """PV generation curve: bell shape centered on noon, peak ~3 kW for villa_pv."""
        pv = [0.0] * SLOTS_PER_DAY
        if not user_input.has_pv:
            return pv

        peak_kw = float(user_input.pv_kwp) * 0.6 if user_input.pv_kwp else 3.0
        for i in range(SLOTS_PER_DAY):
            hour = i * 15 // 60 + (i * 15 % 60) / 60.0
            if 6 <= hour < 20:
                dist_from_noon = abs(hour - 13)
                factor = max(0.0, 1.0 - dist_from_noon / 7.0)
                pv[i] = round(peak_kw * factor, 3)
        return pv
