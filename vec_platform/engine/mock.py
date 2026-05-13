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
    EFFEKTTARIFF_DAY_SEK_PER_KW,
    EFFEKTTARIFF_DAY_START_HOUR,
    EFFEKTTARIFF_DAY_END_HOUR,
    EFFEKTTARIFF_HOUSING,
    SLOTS_PER_DAY,
)


# Phase H: housing_type → archetype mapping. Two engine archetypes:
# apartment (district-heated, N-fix-2 0.15/0.6) and house (heat-pump
# assumption, N-fix-4 0.3/1.0 for villa_pv/pvbess; 0.3/0.9 for noder).
_APARTMENT_HOUSING_TYPES = frozenset({"apt_renting", "apt_condo"})


def _housing_type_from_legacy_ownership(ownership_type):
    """Translate the deprecated ownership_type kwarg to housing_type.

    Phase H one-cycle compat: callers that still pass ownership_type
    instead of housing_type get the closest equivalent — tenant maps
    to renting apartment, owner to the villa-with-meter case. Once
    every caller is migrated this helper can be removed.
    """
    if ownership_type == "tenant":
        return "apt_renting"
    if ownership_type == "owner":
        return "villa_owner"
    return None
# Phase N F9: RETAIL_PRICE_BASE and GRID_FEE_MONTHLY are deprecated
# (replaced by _SE3_SUMMER_RETAIL_SEK_PER_KWH per-slot curve and the
# tiered grid_fee_fixed + GRID_FEE_VARIABLE_RATE respectively). Both
# are intentionally NOT imported above so a stale code path that
# tries to use them fails at import time, not silently.

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
_FEED_IN_PRICE             = 0.40   # SEK/kWh, flat (matches config.FEED_IN_PRICE)


class MockEngine(CalculationEngine):
    """Mock engine with fake data for development."""

    def generate_profile(self, user_input: UserInput) -> DailyProfile:
        """Generate mock 96-slot load profile with per-device breakdown."""

        devices = self._get_devices(user_input)
        base_load = devices["base_load"]
        flexible_load = [
            sum(devices[name][i] for name in devices if name != "base_load")
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
        housing_type: str | None = None,
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
        # Phase N-2: effekttariff for villa owners (Sweden 2026
        # mandate, Ellevio SE3 schedule). Tenants pay the building's
        # shared connection so the peak-kW component does not apply.
        # Mock simplification: use the day-window hourly peak as a
        # one-day proxy for the month's top-3-hour average. Shifting
        # load into the night window (22-06) zeroes the fee — the
        # exact signal the VEC SP experiment wants to surface.
        # Phase H: gate on housing_type instead of the deprecated
        # ownership_type. Apartment owners (BRF condo) and renters
        # share the building's grid connection — only townhouse /
        # villa / other (own-meter) housings are billed individually.
        # Legacy callers passing only ownership_type get a one-cycle
        # translation; NULL housing_type from pre-Phase-H dogfood
        # rows preserves the historical owner-as-villa default.
        if housing_type is None:
            housing_type = _housing_type_from_legacy_ownership(ownership_type)
        if housing_type is None and ownership_type is None:
            # Pre-Phase-H NULL row (172 dogfood sessions): treat as
            # villa_owner so the engine output matches what those
            # rows saw at write-time.
            housing_type = "villa_owner"
        if housing_type in EFFEKTTARIFF_HOUSING:
            hourly_avg_kw = []
            slots_per_hour = SLOTS_PER_DAY // 24  # 4
            for hour in range(24):
                start = hour * slots_per_hour
                slot_vals = (
                    max(0.0, net_load[i])
                    for i in range(start, start + slots_per_hour)
                )
                hourly_avg_kw.append(sum(slot_vals) / slots_per_hour)
            day_peak_kw = max(
                hourly_avg_kw[EFFEKTTARIFF_DAY_START_HOUR:EFFEKTTARIFF_DAY_END_HOUR],
                default=0.0,
            )
            grid_fee += day_peak_kw * EFFEKTTARIFF_DAY_SEK_PER_KW
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
        housing_type = getattr(user_input, "housing_type", None)
        ownership_type = getattr(user_input, "ownership_type", None)
        flex_scale = 0.6 + 0.2 * max(1, int(people))
        # Phase N-fix-5: single-occupancy renting apartments deviate
        # from the default 2-person template more than the linear
        # flex_scale captures. Two adjustments:
        #   A) Dishwasher is absent — only ~20-30% of single-person
        #      50 m² Swedish apartments have one.
        #   B) Washing-machine duration is halved beyond flex_scale
        #      (1-2 cycles/week vs the 2-person 3-4). Implemented by
        #      a direct _device_block call so it bypasses flex_scale.
        # Phase H: gate on housing_type=='apt_renting' (replacing the
        # legacy ownership_type=='tenant'). Falls back to the legacy
        # check for pre-migration NULL rows. Condo owners (apt_condo)
        # are intentionally excluded — they typically have a full
        # apartment-sized appliance kit even when living alone.
        if housing_type is not None:
            single_tenant = (people == 1 and housing_type == "apt_renting")
        else:
            single_tenant = (people == 1 and ownership_type == "tenant")

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
        }

        # Phase N-fix-5 A: skip dishwasher for single tenant.
        if not single_tenant:
            devices["dishwasher#1"] = _scaled_block(78, 84, 1.2)  # 19:30-21:00 base, 1.2 kW

        # Phase N-fix-5 B: single-tenant washing duration capped at 4
        # slots (1h) — approximates 1-2 cycles/week vs the 2-person
        # 3-4. Non-single cases keep the flex_scale-adjusted duration.
        if single_tenant:
            devices["washing_machine#1"] = self._device_block(76, 80, 2.0)  # 19:00-20:00, 1h
        else:
            devices["washing_machine#1"] = _scaled_block(76, 84, 2.0)  # 19:00-21:00 base, 2.0 kW

        # v3 dropped the heating question along with the water_heater device.

        # EV charging late afternoon (16:00-20:00, 4h).
        # Kept non-wrapping so the Step 3 timeline can show it as a single block.
        # Phase N-fix-3: NOT flex-scaled (single vehicle, not per-person).
        # Phase N-fix-4: duration halved 32→16 slots (8h→4h). Real
        # Swedish commuter EV draws ~9 kWh/day (50 km × 0.18 kWh/km),
        # which 4h × 3.7 kW = 14.8 kWh comfortably covers with headroom.
        # The 8h default was producing 888 kWh/mo (3.3x real ~270).
        if user_input.has_ev:
            devices["ev_charger#1"] = self._device_block(64, 80, 3.7)

        return devices

    @staticmethod
    def _derive_building_type(user_input: UserInput) -> str:
        """Map v3 housing + DER → engine archetype code.

        Internal helper only; the engine still drives base-load amplitude
        with these archetypes (Phase N-fix-2 / -4 calibrated):
          apartment         (apt_renting / apt_condo)         0.15 / 0.6
          villa_noder       (house, no PV)                    0.3  / 0.9
          villa_pv          (house, has PV no BESS)           0.3  / 1.0
          villa_pvbess      (house, has PV + BESS)            0.3  / 1.0

        Phase H: prefers ``housing_type`` (apt_renting / apt_condo /
        townhouse_owner / villa_owner / other). Falls back to the legacy
        ``ownership_type`` for rows written before the migration, and
        finally to the house archetype for pre-pilot NULL dogfood rows.
        """
        housing_type = getattr(user_input, "housing_type", None)
        if housing_type in _APARTMENT_HOUSING_TYPES:
            return "apartment"
        if housing_type is None:
            # Legacy / pre-Phase-H row — fall back to ownership_type.
            if user_input.ownership_type == "tenant":
                return "apartment"
        # All non-apartment housing_type values (townhouse / villa /
        # other) plus NULL+owner legacy fall into the house branch.
        if user_input.has_pv and user_input.has_bess:
            return "villa_pvbess"
        if user_input.has_pv:
            return "villa_pv"
        return "villa_noder"

    @staticmethod
    def _device_block(start_slot: int, end_slot: int, kw: float) -> list:
        """Create a 96-slot array with `kw` between start_slot (inclusive) and end_slot (exclusive)."""
        arr = [0.0] * SLOTS_PER_DAY
        for i in range(start_slot, end_slot):
            arr[i] = kw
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
