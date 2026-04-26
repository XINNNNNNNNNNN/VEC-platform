"""Session API endpoints."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db
from vec_platform.models import Session as SessionModel

router = APIRouter()


class SessionCreate(BaseModel):
    role: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    created_at: datetime
    completed: bool
    current_step: int
    role: Optional[str]

    class Config:
        from_attributes = True


@router.post("/session", response_model=SessionResponse)
def create_session(db: Session = Depends(get_db)):
    """Create a new session."""
    session_id = str(uuid.uuid4())
    session = SessionModel(
        id=session_id,
        created_at=datetime.utcnow(),
        current_step=1,
        completed=False,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Get session by ID."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.put("/session/{session_id}/step")
def update_session_step(
    session_id: str, 
    step: int,
    db: Session = Depends(get_db)
):
    """Update session current step."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.current_step = step
    db.commit()
    return {"status": "ok", "current_step": step}


@router.put("/session/{session_id}/complete")
def complete_session(session_id: str, db: Session = Depends(get_db)):
    """Mark session as completed."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.completed = True
    session.current_step = 8
    db.commit()
    return {"status": "ok", "completed": True}