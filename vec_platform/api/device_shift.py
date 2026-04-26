"""Device shift and drag log API endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db
from vec_platform.models import Session as SessionModel, DeviceShift, DragLog

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