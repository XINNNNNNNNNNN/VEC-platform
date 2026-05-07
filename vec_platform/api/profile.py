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
    else:
        has_pv = has_bess = has_ev = False

    return {
        "session_id": profile.session_id,
        "step": profile.step,
        "rigid_load": json.loads(profile.rigid_load),
        "flexible_load": json.loads(profile.flexible_load),
        "pv_generation": json.loads(profile.pv_generation),
        "net_load": json.loads(profile.net_load),
        "devices": json.loads(profile.devices),
        "has_pv": has_pv,
        "has_bess": has_bess,
        "has_ev": has_ev,
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
    # v3.4: Step 3 baseline ±10% adjuster, in 5% steps. The frontend has
    # already applied this scale to the base load it shows the user; we
    # store the factor as metadata so downstream pages can recover the
    # un-scaled view if needed.
    scale_factor: float = 1.0


@router.post("/recalculate")
def recalculate(
    data: RecalculateRequest,
    db: Session = Depends(get_db),
):
    """Rebuild the profile from new device positions and compute a fresh bill.

    Uses the base_load and PV generation from the Step 2 baseline profile,
    overlays the submitted device positions to produce a new per-device
    breakdown, persists it at `step=data.step`, and returns chart-ready data
    plus a bill for `data.scenario`.
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
    pv_generation = json.loads(baseline.pv_generation)

    # Apply Step 3's baseline scale to the rigid load (and ONLY the rigid
    # load — PV generation and shiftable devices stay at their nominal
    # values, since the ±10% knob represents passive-load uncertainty).
    scale = float(data.scale_factor)
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

    flexible_load = [
        # Skip non-array metadata (e.g. __scale_factor__) when summing.
        sum(
            devices[name][i]
            for name in devices
            if name != "base_load" and not name.startswith("__")
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
    for scenario in ("no_vec", "vec_no_adjust", "vec_adjusted"):
        bill = calculation_engine.calculate_bill(profile, scenario)
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