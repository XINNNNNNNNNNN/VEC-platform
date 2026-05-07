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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db
from vec_platform.models import UserInput

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

    db.commit()
    return {"status": "ok", "touched": touched}
