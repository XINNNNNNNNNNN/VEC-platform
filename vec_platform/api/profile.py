"""Profile API endpoints."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db, calculation_engine
from vec_platform.models import (
    Session as SessionModel,
    UserInput,
    DailyProfile,
    BillBreakdown,
)
from vec_platform.config import SLOTS_PER_DAY

router = APIRouter()


class UserInputCreate(BaseModel):
    session_id: str
    building_type: str
    area_m2: float
    people: int
    heating: str
    has_ev: bool = False
    has_pv: bool = False
    pv_kwp: Optional[float] = None
    has_bess: bool = False
    bess_kwh: Optional[float] = None


class ProfileResponse(BaseModel):
    id: int
    session_id: str
    step: int
    rigid_load: str
    flexible_load: str
    pv_generation: str
    net_load: str
    devices: str

    class Config:
        from_attributes = True


@router.post("/user-input")
def create_user_input(
    data: UserInputCreate,
    db: Session = Depends(get_db)
):
    """Create user input and generate profile."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Create user input
    user_input = UserInput(
        session_id=data.session_id,
        building_type=data.building_type,
        area_m2=data.area_m2,
        people=data.people,
        heating=data.heating,
        has_ev=data.has_ev,
        has_pv=data.has_pv,
        pv_kwp=data.pv_kwp,
        has_bess=data.has_bess,
        bess_kwh=data.bess_kwh,
    )
    db.add(user_input)
    db.commit()
    db.refresh(user_input)
    
    # Update session role
    session.role = data.building_type
    db.commit()
    
    # Generate profile using engine
    profile = calculation_engine.generate_profile(user_input)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    
    return {
        "status": "ok",
        "session_id": data.session_id,
        "profile_id": profile.id,
    }


@router.get("/profile/{session_id}")
def get_profile(
    session_id: str,
    step: int = 2,
    db: Session = Depends(get_db)
):
    """Get profile for a session."""
    profile = db.query(DailyProfile).filter(
        DailyProfile.session_id == session_id,
        DailyProfile.step == step
    ).first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Phase 3.X-fix-18: surface has_bess so Step 3 can render the BESS
    # placeholder track (display-only; auto-managed simulation deferred).
    # Phase B: also surface has_pv / has_ev so the calibration panel
    # can conditionally render the matching capacity-input rows.
    # Phase C: surface the persisted calibration values + calibrated
    # flags so the panel can restore UI state on reload.
    user_input = (
        db.query(UserInput)
        .filter(UserInput.session_id == session_id)
        .order_by(UserInput.id.desc())
        .first()
    )
    if user_input is not None:
        has_pv = bool(user_input.has_pv)
        has_bess = bool(user_input.has_bess)
        has_ev = bool(user_input.has_ev)
        pv_kwp = user_input.pv_kwp
        bess_kwh = user_input.bess_kwh
        ev_kwh = user_input.ev_kwh
        load_scale_factor = (
            user_input.load_scale_factor
            if user_input.load_scale_factor is not None
            else 1.0
        )
        pv_calibrated = bool(user_input.pv_calibrated)
        bess_calibrated = bool(user_input.bess_calibrated)
        ev_calibrated = bool(user_input.ev_calibrated)
    else:
        has_pv = has_bess = has_ev = False
        pv_kwp = bess_kwh = ev_kwh = None
        load_scale_factor = 1.0
        pv_calibrated = bess_calibrated = ev_calibrated = False

    # Phase D-1: recompute PV generation on the fly from the current
    # user_inputs.pv_kwp instead of returning the frozen baseline
    # snapshot. The Step-1 baseline daily_profiles row stays
    # untouched, but the JS state is primed with the calibration-aware
    # curve so the live chart + bill match what the participant has
    # dialed in. Phase D-2: extend this to step=3 too — when
    # timeline.js loads the user's saved customized profile (devices),
    # it should still see fresh PV reflecting any post-Next
    # calibration changes.
    #
    # Note: ``rigid_load`` is intentionally returned UN-scaled —
    # timeline.js applies ``load_scale_factor`` client-side on every
    # ±5% click, and prime that scale via ``state.scaleFactor`` on
    # initial load. Pre-scaling here would double-multiply.
    rigid_load_arr = json.loads(profile.rigid_load)
    pv_generation_arr = json.loads(profile.pv_generation)
    if user_input is not None:
        # Phase K-2 F1+F2: re-derive rigid_load from current user_input
        # so changes to area_m2 / people / building_type flow through
        # to the baseline view without needing to rewrite step=2 in
        # the DB. (PV re-derive below was Phase D-1; F2 extends the
        # same pattern to the rigid load.)
        building_type = calculation_engine._derive_building_type(user_input)
        rigid_load_arr = calculation_engine._get_base_load(
            building_type,
            area_m2=user_input.area_m2,
            people=user_input.people,
        )
        if has_pv:
            pv_generation_arr = calculation_engine._get_pv_generation(user_input)
        else:
            pv_generation_arr = [0.0] * SLOTS_PER_DAY
        # Phase D-2: when serving step!=2 (e.g. step=3 for device
        # restore), the matching daily_profiles row's ``rigid_load``
        # is the *scaled* base load that recalculate wrote. JS
        # consumes this field as the un-scaled baseline and applies
        # ``load_scale_factor`` itself, so we must always return the
        # un-scaled view. Pull it from the step=2 baseline (which
        # step1.py wrote untouched).
        if step != 2:
            baseline = (
                db.query(DailyProfile)
                .filter(
                    DailyProfile.session_id == session_id,
                    DailyProfile.step == 2,
                )
                .order_by(DailyProfile.id.desc())
                .first()
            )
            if baseline is not None:
                rigid_load_arr = json.loads(baseline.rigid_load)

    return {
        "session_id": profile.session_id,
        "step": profile.step,
        "rigid_load": rigid_load_arr,
        "flexible_load": json.loads(profile.flexible_load),
        "pv_generation": pv_generation_arr,
        "net_load": json.loads(profile.net_load),
        "devices": json.loads(profile.devices),
        "has_pv": has_pv,
        "has_bess": has_bess,
        "has_ev": has_ev,
        # Phase C: calibration state for UI restore.
        "pv_kwp": pv_kwp,
        "bess_kwh": bess_kwh,
        "ev_kwh": ev_kwh,
        "load_scale_factor": load_scale_factor,
        "pv_calibrated": pv_calibrated,
        "bess_calibrated": bess_calibrated,
        "ev_calibrated": ev_calibrated,
        # Phase N F6: surface area_m2 so JS computeBillScenario uses
        # the same tiered grid fee as the backend, keeping /step3
        # live preview consistent with /step5 Compare and the DB.
        "area_m2": (user_input.area_m2 if user_input is not None else None),
        # Phase O: surface building_type so the JS live preview can
        # select the same engine archetype as the backend. The Phase
        # N-2 ownership_type field is no longer returned — JS no
        # longer needs it because effekttariff was removed.
        "building_type": (
            getattr(user_input, "building_type", None)
            if user_input is not None else None
        ),
    }


class DevicePosition(BaseModel):
    name: str
    start_slot: int
    duration_slots: int
    load_kw: float


class RecalculateRequest(BaseModel):
    session_id: str
    step: int = 3
    scenario: str = "no_vec"
    device_positions: list[DevicePosition]
    # v3.4: Step 3 baseline ±10% adjuster, in 5% steps. Phase D-1
    # demoted this field from authoritative to ignored — the recalc
    # path now reads ``user_inputs.load_scale_factor`` instead. The
    # field is retained on the request schema for backward compat
    # so older clients (or any cached JS) don't 422 on submit.
    scale_factor: float = 1.0


@router.post("/recalculate")
def recalculate(
    data: RecalculateRequest,
    db: Session = Depends(get_db),
):
    """Rebuild the profile from new device positions and compute a fresh bill.

    Uses the base_load from the Step 2 baseline profile, recomputes PV
    generation from current user_inputs.pv_kwp, applies the persisted
    load_scale_factor, overlays the submitted device positions to
    produce a new per-device breakdown, persists at ``step=data.step``,
    and returns chart-ready data plus a bill for ``data.scenario``.

    Phase D-1 changes:
    * PV curve is regenerated from ``user_inputs.pv_kwp`` instead of
      reusing the frozen baseline snapshot — Phase C calibration of
      PV capacity now reaches the bill.
    * ``load_scale_factor`` is read from ``user_inputs`` rather than
      the JS payload. The payload's ``scale_factor`` field is retained
      for backward compat (older clients won't 422) but ignored.
    """
    baseline = (
        db.query(DailyProfile)
        .filter(DailyProfile.session_id == data.session_id, DailyProfile.step == 2)
        .order_by(DailyProfile.id.desc())
        .first()
    )
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline profile not found")

    raw_base_load = json.loads(baseline.rigid_load)

    # Phase D-1: read calibration from user_inputs as the source of truth.
    user_input = (
        db.query(UserInput)
        .filter(UserInput.session_id == data.session_id)
        .order_by(UserInput.id.desc())
        .first()
    )
    if user_input is not None:
        scale = float(
            user_input.load_scale_factor
            if user_input.load_scale_factor is not None
            else 1.0
        )
        if user_input.has_pv:
            pv_generation = calculation_engine._get_pv_generation(user_input)
        else:
            pv_generation = [0.0] * SLOTS_PER_DAY
    else:
        # No user_input row (defensive — shouldn't happen post-Step-1).
        # Fall back to the frozen baseline's PV curve and identity scale.
        scale = 1.0
        pv_generation = json.loads(baseline.pv_generation)

    # Apply baseline scale to the rigid load only — PV generation and
    # shiftable device loads stay nominal.
    base_load = [v * scale for v in raw_base_load]

    devices: dict[str, list[float]] = {"base_load": base_load}
    for pos in data.device_positions:
        # Phase 3.X-fix-18: wrap-aware slot fill so a device that crosses
        # midnight (start=90, duration=20) actually contributes load on
        # both sides of the cycle. Pre-fix-18 the loop clipped at
        # SLOTS_PER_DAY and silently dropped the wrapped tail, so the
        # bill diverged from what the user saw on the wrapped timeline.
        arr = [0.0] * SLOTS_PER_DAY
        start = pos.start_slot % SLOTS_PER_DAY
        duration = max(0, min(SLOTS_PER_DAY, pos.duration_slots))
        for i in range(duration):
            arr[(start + i) % SLOTS_PER_DAY] = pos.load_kw
        devices[pos.name] = arr

    # Stash scale_factor as metadata. Underscore-prefixed keys are skipped
    # by every reader of the devices dict (timeline.js, step5.js use
    # ``Array.isArray`` guards; Step 2's chart uses an explicit allowlist).
    devices["__scale_factor__"] = scale

    # Phase O-fix-2: BESS schedule keys live in devices alongside
    # cooking / EV but are NOT loads — storage redirects flow. They
    # are excluded from flexible_load here; the bill dispatcher
    # (mock._apply_bess_dispatch) folds their effect into net_load
    # at bill-computation time.
    _BESS_KEYS = ("bess_charge#1", "bess_discharge#1")
    flexible_load = [
        # Skip non-array metadata (e.g. __scale_factor__) when summing.
        sum(
            devices[name][i]
            for name in devices
            if name != "base_load"
            and not name.startswith("__")
            and name not in _BESS_KEYS
        )
        for i in range(SLOTS_PER_DAY)
    ]
    net_load = [
        base_load[i] + flexible_load[i] - pv_generation[i]
        for i in range(SLOTS_PER_DAY)
    ]

    # Replace any existing profile at this step for this session.
    db.query(DailyProfile).filter(
        DailyProfile.session_id == data.session_id,
        DailyProfile.step == data.step,
    ).delete(synchronize_session=False)

    profile = DailyProfile(
        session_id=data.session_id,
        step=data.step,
        rigid_load=json.dumps(base_load),
        flexible_load=json.dumps(flexible_load),
        pv_generation=json.dumps(pv_generation),
        net_load=json.dumps(net_load),
        devices=json.dumps(devices),
    )
    db.add(profile)
    db.flush()

    # Recompute bill for the requested scenario (and any others we already track).
    db.query(BillBreakdown).filter(
        BillBreakdown.session_id == data.session_id,
        BillBreakdown.step == data.step,
    ).delete(synchronize_session=False)

    bills = {}
    # Phase N F6: area_m2 from user_input drives tiered grid_fee.
    # Phase O: building_type drives the 2-archetype split.
    # ownership_type is no longer consulted (effekttariff removed).
    area_m2 = user_input.area_m2 if user_input is not None else None
    building_type = (
        getattr(user_input, "building_type", None)
        if user_input is not None else None
    )
    for scenario in ("no_vec", "vec_no_adjust", "vec_adjusted"):
        bill = calculation_engine.calculate_bill(
            profile, scenario,
            area_m2=area_m2,
            building_type=building_type,
        )
        db.add(bill)
        bills[scenario] = {
            "energy_purchase": bill.energy_purchase,
            "grid_fee": bill.grid_fee,
            "energy_tax": bill.energy_tax,
            "pv_self_consumption": bill.pv_self_consumption,
            "vec_discount": bill.vec_discount,
            "feed_in_income": bill.feed_in_income,
            "net_cost": bill.net_cost,
        }

    db.commit()

    return {
        "session_id": data.session_id,
        "step": data.step,
        "devices": devices,
        "pv_generation": pv_generation,
        "net_load": net_load,
        "bill": bills[data.scenario],
        "bills": bills,
    }