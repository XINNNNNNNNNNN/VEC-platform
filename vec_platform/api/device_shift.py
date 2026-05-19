"""Device shift and drag log API endpoints."""

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db
from vec_platform.models import (
    Session as SessionModel,
    DeviceShift,
    DragLog,
    PriorExpectation,
)

router = APIRouter()


class DeviceShiftCreate(BaseModel):
    session_id: str
    step: int
    device_name: str
    original_start: int
    original_end: int
    final_start: int
    final_end: int
    willing: Optional[bool] = None
    unwilling_reason: Optional[str] = None

    # v3.4 piggyback fields. Step 3's confirm flow now also collects a
    # second prior-expectation guess + confidence Likert. The frontend
    # sends these on a single (typically the first) device-shift call to
    # avoid an extra round-trip; backend writes one PriorExpectation row
    # when step == 3 and both fields are present. Other steps ignore them.
    prior_expectation_pct: Optional[float] = None
    confidence: Optional[int] = None

    # v3.6 piggyback fields. The respond page's confirm flow collects a
    # counter-factual + a perceived-effort question. Same first-shift-
    # only pattern; backend upserts into survey_responses when step==5.
    #
    # Phase 4-A: DB columns renamed step5_* -> step4_* (the respond page
    # is now Step 4 in the 7-step flow). The q2 wire field retained the
    # step5_* prefix because it's keyed by the data.step value (still
    # =5 per decision 2a), and the JS const STEP=5 in step5.js is
    # preserved per decision 1B. Mapping happens server-side below.
    #
    # Phase Q-3-followup: q1 redesigned from single-select enum
    # ('yes'/'no'/'maybe') into a conditional per-device reservation-
    # price list. The wire field is renamed to match the new DB
    # column name (step4_q1_reconsider_devices). Wire value shape:
    #   None  -> user has zero willing=False devices (DB write NULL)
    #   []    -> user picked the "None" sentinel (DB write '[]')
    #   ["EV", "Oven"] -> reconsider list (DB write JSON-serialized)
    step4_q1_reconsider_devices: Optional[List[str]] = None
    step5_q2_effort: Optional[str] = None
    # ^ 'easy' / 'acceptable' / 'disruptive' / 'none'


class DragLogCreate(BaseModel):
    session_id: str
    step: int
    device_name: str
    from_start: int
    from_end: int
    to_start: int
    to_end: int
    action: str = "move"


@router.post("/device-shift")
def create_device_shift(
    data: DeviceShiftCreate,
    db: Session = Depends(get_db)
):
    """Save device shift positions."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Create device shift
    shift = DeviceShift(
        session_id=data.session_id,
        step=data.step,
        device_name=data.device_name,
        original_start=data.original_start,
        original_end=data.original_end,
        final_start=data.final_start,
        final_end=data.final_end,
        willing=data.willing,
        unwilling_reason=data.unwilling_reason,
    )
    db.add(shift)

    # v3.4 / Phase E: piggyback the second prior-expectation guess
    # from the customize page's confirm flow. Only writes when
    # step == 3 AND both fields are sent. Pre-Phase E this used a
    # "skip if existing" guard which silently dropped the new value
    # on resubmit; now it upserts so the participant's latest answer
    # is recorded. The piggyback path still fires only on the first
    # device-shift call per submit, so a typical Next produces a
    # single upsert.
    if (
        data.step == 3
        and data.prior_expectation_pct is not None
        and data.confidence is not None
    ):
        from vec_platform.pages._upsert_helpers import upsert_prior_expectation
        upsert_prior_expectation(
            db, data.session_id,
            measurement_round=2,
            pct=data.prior_expectation_pct,
            confidence=data.confidence,
        )

    # v3.6 / Phase 4-A / Phase Q-3-followup: piggyback the reservation-
    # price list + effort answers from the respond page's confirm flow.
    # Same idempotent pattern (always overwrite — Phase E). Gate is now
    # q2 alone because q1 is legitimately None when the participant
    # has zero willing=False devices (S4-Q1 card hidden) — gating on
    # q1 being non-None would drop the q2 write in the all-willing
    # case.
    if (
        data.step == 5
        and data.step5_q2_effort is not None
    ):
        from vec_platform.pages._survey_helpers import get_or_create_survey_row
        row = get_or_create_survey_row(db, data.session_id)
        # q1: None -> DB NULL (no willing=False devices, question
        # didn't apply); list -> JSON-serialized (including [] for
        # the "None" sentinel — distinguishable from NULL because
        # it means the user saw the question and explicitly picked
        # "wouldn't change my mind for any of these").
        if data.step4_q1_reconsider_devices is None:
            row.step4_q1_reconsider_devices = None
        else:
            row.step4_q1_reconsider_devices = json.dumps(
                list(data.step4_q1_reconsider_devices)
            )
        row.step4_q2_effort = data.step5_q2_effort

    db.commit()
    db.refresh(shift)

    return {
        "status": "ok",
        "shift_id": shift.id,
    }


@router.get("/device-shift/{session_id}")
def get_device_shifts(
    session_id: str,
    step: int,
    db: Session = Depends(get_db)
):
    """Get device shifts for a session."""
    shifts = db.query(DeviceShift).filter(
        DeviceShift.session_id == session_id,
        DeviceShift.step == step
    ).all()
    
    return [
        {
            "device_name": s.device_name,
            "original_start": s.original_start,
            "original_end": s.original_end,
            "final_start": s.final_start,
            "final_end": s.final_end,
            "willing": s.willing,
            "unwilling_reason": s.unwilling_reason,
        }
        for s in shifts
    ]


@router.post("/drag-log")
def create_drag_log(
    data: DragLogCreate,
    db: Session = Depends(get_db)
):
    """Log a drag operation."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Create drag log
    log = DragLog(
        session_id=data.session_id,
        step=data.step,
        timestamp=datetime.utcnow(),
        device_name=data.device_name,
        from_start=data.from_start,
        from_end=data.from_end,
        to_start=data.to_start,
        to_end=data.to_end,
        action=data.action,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    
    return {
        "status": "ok",
        "log_id": log.id,
    }


@router.get("/drag-log/{session_id}")
def get_drag_logs(
    session_id: str,
    step: int,
    db: Session = Depends(get_db)
):
    """Get drag logs for a session."""
    logs = db.query(DragLog).filter(
        DragLog.session_id == session_id,
        DragLog.step == step
    ).order_by(DragLog.timestamp).all()
    
    return [
        {
            "timestamp": log.timestamp.isoformat(),
            "device_name": log.device_name,
            "from_start": log.from_start,
            "from_end": log.from_end,
            "to_start": log.to_start,
            "to_end": log.to_end,
            "action": log.action,
        }
        for log in logs
    ]