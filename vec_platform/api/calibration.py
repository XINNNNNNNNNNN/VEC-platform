"""Phase C: Step 3 calibration persistence endpoint.

The calibration UI in static/js/timeline.js (VECCalibration) PUTs to
this endpoint every time the participant adjusts a capacity input,
toggles "I don't know", or steps the ±5% baseline scaler. Writes are
debounced client-side (~300 ms) so a flurry of clicks coalesces into
one round-trip.

Per Phase C decision matrix (option A): pv_kwp / bess_kwh are reused
as the canonical capacity columns; ev_kwh / load_scale_factor /
pv_calibrated / bess_calibrated / ev_calibrated were added by the
Phase C alembic migration. The endpoint patches only the fields the
client explicitly sends — pydantic v2 ``model_fields_set`` makes that
distinction reliably.

Engine wiring is NOT changed in Phase C — the bill calculation still
reads ``pv_kwp`` from the same column (which fix-18's recalculate
path already consumes) and ignores ``bess_kwh`` / ``ev_kwh`` /
``load_scale_factor``. Phase D will switch the engine over to read
all four values from this column set.
"""
import json as _json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db
from vec_platform.models import BillBreakdown, DailyProfile, UserInput
from vec_platform.runtime import calculation_engine

router = APIRouter()


class CalibrationUpdate(BaseModel):
    session_id: str
    # Capacity values. Sent on every change; "I don't know" toggling
    # leaves the value alone but flips the matching `*_calibrated`.
    pv_kwp: Optional[float] = None
    bess_kwh: Optional[float] = None
    ev_kwh: Optional[float] = None
    load_scale_factor: Optional[float] = None
    # Research signal: did the participant actively confirm this value?
    pv_calibrated: Optional[bool] = None
    bess_calibrated: Optional[bool] = None
    ev_calibrated: Optional[bool] = None


_PATCHABLE_FIELDS = (
    "pv_kwp", "bess_kwh", "ev_kwh", "load_scale_factor",
    "pv_calibrated", "bess_calibrated", "ev_calibrated",
)

# Phase K-2 fix-1: subset of patchable fields whose change actually
# alters the step=2 baseline numbers. Toggling the *_calibrated flags
# alone does not need a cascade write — they only record "did the
# participant actively confirm this value".
_AFFECTS_BASELINE = ("pv_kwp", "bess_kwh", "ev_kwh", "load_scale_factor")

_CASCADE_SCENARIOS = ("no_vec", "vec_no_adjust", "vec_adjusted")


def _cascade_rewrite_step2_baseline(db: Session, ui: UserInput) -> None:
    """Phase K-2 fix-1: rebuild daily_profiles + bill_breakdowns step=2.

    /step5 _pick_scenario_bill (Phase K-2 F1) lazy-regenerates step=2
    bill from the current ``user_inputs`` row on every read, so the
    frontend Compare card always reflects calibration. The persisted
    DB rows, however, stayed frozen at Step 1 submit values — a PV
    calibration from 5 to 15 kWp would leave bill_breakdowns step=2
    showing the pv_kwp=5 number. SQL audit joining user_inputs to
    bill_breakdowns would then read inconsistent state.

    This helper rewrites the step=2 baseline so the persisted numbers
    match what _pick_scenario_bill computes (and what /step3
    timeline.js displays live). Only step=2 is touched — step=3 and
    step=5 rows are produced by /api/recalculate and Step 4/5
    callbacks respectively, and are independent of the baseline.

    ``rigid_load`` is persisted UN-scaled (matches the api/profile.py
    convention; JS reapplies load_scale_factor). ``net_load`` is the
    scaled curve so calculate_bill — which integrates net_load against
    the SE3 retail curve (Phase K-2 F4) — produces the same number
    /step5 lazy-regen would.
    """
    sid = ui.session_id

    db.query(BillBreakdown).filter(
        BillBreakdown.session_id == sid,
        BillBreakdown.step == 2,
    ).delete(synchronize_session=False)
    db.query(DailyProfile).filter(
        DailyProfile.session_id == sid,
        DailyProfile.step == 2,
    ).delete(synchronize_session=False)
    db.flush()

    fresh = calculation_engine.generate_profile(ui)
    scale = float(ui.load_scale_factor or 1.0)
    rigid_unscaled = _json.loads(fresh.rigid_load)
    rigid_scaled = [v * scale for v in rigid_unscaled]
    flex = _json.loads(fresh.flexible_load)
    pv = _json.loads(fresh.pv_generation)
    net_scaled = [
        rigid_scaled[i] + flex[i] - pv[i] for i in range(len(rigid_unscaled))
    ]

    profile_row = DailyProfile(
        session_id=sid,
        step=2,
        rigid_load=fresh.rigid_load,
        flexible_load=fresh.flexible_load,
        pv_generation=fresh.pv_generation,
        net_load=_json.dumps(net_scaled),
        devices=fresh.devices,
    )
    db.add(profile_row)
    db.flush()

    for scenario in _CASCADE_SCENARIOS:
        # Phase N F6: area_m2 drives the tiered grid_fee_fixed so the
        # cascade-rewritten step=2 bill matches what other callers
        # (step1, recalculate, lazy regen) produce.
        # Phase N-2: ownership_type for villa effekttariff.
        db.add(calculation_engine.calculate_bill(
            profile_row, scenario,
            area_m2=ui.area_m2,
            ownership_type=ui.ownership_type,
        ))


@router.put("/user_input/calibration")
def update_calibration(
    payload: CalibrationUpdate,
    db: Session = Depends(get_db),
):
    """Patch calibration fields on the session's user_input row.

    Only fields explicitly present in the request body are written;
    anything omitted is left untouched. ``model_fields_set`` (pydantic
    v2) returns the names of fields the client actually sent — a
    field omitted from the body is *not* in the set even if its
    pydantic default is ``None``.
    """
    ui = (
        db.query(UserInput)
        .filter(UserInput.session_id == payload.session_id)
        .order_by(UserInput.id.desc())
        .first()
    )
    if ui is None:
        raise HTTPException(
            status_code=404,
            detail=f"user_input not found for session {payload.session_id}",
        )

    explicit = payload.model_fields_set
    touched = []
    for field in _PATCHABLE_FIELDS:
        if field in explicit:
            setattr(ui, field, getattr(payload, field))
            touched.append(field)

    if not touched:
        # No fields to patch — short-circuit before commit.
        return {"status": "ok", "touched": []}

    # Phase K-2 fix-1: cascade-rewrite the step=2 baseline so SQL
    # audit and /step5 lazy regen produce the same numbers. Only
    # triggered when a capacity / scale field changed; flipping a
    # *_calibrated flag alone does not alter the profile or bill.
    if any(f in _AFFECTS_BASELINE for f in touched):
        db.flush()
        _cascade_rewrite_step2_baseline(db, ui)

    db.commit()
    return {"status": "ok", "touched": touched}
