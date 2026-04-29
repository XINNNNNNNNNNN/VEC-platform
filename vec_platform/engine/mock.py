"""Mock calculation engine with fake data for development."""

import json

from vec_platform.engine.base import CalculationEngine
from vec_platform.models import UserInput, DailyProfile, BillBreakdown, ShadowPrices
from vec_platform.config import (
    RETAIL_PRICE_BASE,
    GRID_FEE_MONTHLY,
    ENERGY_TAX,
    VEC_INTERNAL_BUY,
    VEC_INTERNAL_SELL,
    FEED_IN_PRICE,
    SLOTS_PER_DAY,
)

DAYS_PER_MONTH = 30


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
    ) -> BillBreakdown:
        """Calculate a monthly bill breakdown for one scenario."""

        net_load = json.loads(profile.net_load)
        pv_gen = json.loads(profile.pv_generation)

        # Convert per-slot kW to daily kWh, then to monthly.
        consumed_daily = sum(max(0.0, x) for x in net_load) * 0.25
        exported_daily = sum(max(0.0, -x) for x in net_load) * 0.25
        pv_daily = sum(pv_gen) * 0.25

        consumed_monthly = consumed_daily * DAYS_PER_MONTH
        exported_monthly = exported_daily * DAYS_PER_MONTH
        pv_monthly = pv_daily * DAYS_PER_MONTH

        energy_purchase = consumed_monthly * RETAIL_PRICE_BASE
        grid_fee = GRID_FEE_MONTHLY
        tax = consumed_monthly * ENERGY_TAX

        # PV self-consumption value (assume PV first offsets own load)
        self_consumed_monthly = max(0.0, pv_monthly - exported_monthly)
        pv_self_consumption = self_consumed_monthly * RETAIL_PRICE_BASE

        if scenario == "no_vec":
            vec_discount = 0.0
            feed_in_income = exported_monthly * FEED_IN_PRICE
        elif scenario == "vec_no_adjust":
            vec_discount = consumed_monthly * 0.15
            feed_in_income = exported_monthly * VEC_INTERNAL_SELL
        else:  # vec_adjusted
            vec_discount = consumed_monthly * 0.25
            feed_in_income = exported_monthly * VEC_INTERNAL_SELL

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
        """Get mock shadow prices (same for all users)."""

        retail = []
        internal_buy = []
        internal_sell = []
        feed_in = []

        for slot in range(SLOTS_PER_DAY):
            hour = slot * 15 // 60

            if 7 <= hour < 9 or 17 <= hour < 21:
                retail_price = RETAIL_PRICE_BASE + 0.5
            elif 22 <= hour or hour < 6:
                retail_price = RETAIL_PRICE_BASE - 0.3
            else:
                retail_price = RETAIL_PRICE_BASE
            retail.append(round(retail_price, 2))

            if 10 <= hour < 14:
                internal_buy.append(VEC_INTERNAL_BUY - 0.1)
            else:
                internal_buy.append(VEC_INTERNAL_BUY)

            internal_sell.append(VEC_INTERNAL_SELL)
            feed_in.append(FEED_IN_PRICE)

        return ShadowPrices(
            session_id=session_id,
            retail_price=json.dumps(retail),
            internal_buy=json.dumps(internal_buy),
            internal_sell=json.dumps(internal_sell),
            feed_in_price=json.dumps(feed_in),
        )

    # -------- Internal helpers --------

    def _get_base_load(self, building_type: str) -> list:
        """Rigid baseline: fridge/lighting/standby + morning & evening peaks.

        Spec:
          apartment: base 0.3 kW, peak 1.2 kW (06-09, 17-22)
          villa_pv / villa_pvbess: base 0.5 kW, peak 1.8 kW
          villa_noder: base 0.5 kW, peak 1.5 kW
        """
        if building_type == "apartment":
            base, peak = 0.3, 1.2
        elif building_type == "villa_noder":
            base, peak = 0.5, 1.5
        else:  # villa_pv, villa_pvbess
            base, peak = 0.5, 1.8

        load = [base] * SLOTS_PER_DAY
        for i in range(SLOTS_PER_DAY):
            hour = i * 15 // 60
            if 6 <= hour < 9 or 17 <= hour < 22:
                load[i] = peak
        return load

    def _get_devices(self, user_input: UserInput) -> dict:
        """Per-device 96-slot load arrays (kW)."""
        devices: dict[str, list[float]] = {
            "base_load": self._get_base_load(user_input.building_type),
            # Cooking is short and not really shiftable, but show it.
            "cooking_am": self._device_block(28, 30, 2.0),  # 07:00-07:30
            "cooking_pm": self._device_block(72, 76, 2.0),  # 18:00-19:00
            # Shiftable wet appliances.
            "dishwasher": self._device_block(78, 84, 1.2),  # 19:30-21:00
            "washing_machine": self._device_block(76, 84, 0.5),  # 19:00-21:00
        }

        # Electric / heat-pump households add a water heater pre-shower.
        if user_input.heating in {"electric", "heatpump"}:
            devices["water_heater"] = self._device_block(20, 28, 3.0)  # 05-07

        # EV charging late afternoon through midnight (16:00-24:00, 8h).
        # Kept non-wrapping so the Step 3 timeline can show it as a single block.
        if user_input.has_ev:
            devices["ev_charger"] = self._device_block(64, 96, 3.7)

        return devices

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
