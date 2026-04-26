"""Survey API endpoints."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db, calculation_engine
from vec_platform.models import Session as SessionModel, SurveyResponse

router = APIRouter()


class SurveyCreate(BaseModel):
    session_id: str
    q1_willingness: str
    q2_reasons: list[str]
    q3_concerns: list[str]
    q4_savings_perception: str


@router.post("/survey")
def create_survey(
    data: SurveyCreate,
    db: Session = Depends(get_db)
):
    """Save survey response."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == data.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Create survey response
    survey = SurveyResponse(
        session_id=data.session_id,
        q1_willingness=data.q1_willingness,
        q2_reasons=json.dumps(data.q2_reasons),
        q3_concerns=json.dumps(data.q3_concerns),
        q4_savings_perception=data.q4_savings_perception,
    )
    db.add(survey)
    
    # Mark session as completed
    session.completed = True
    session.current_step = 8
    
    db.commit()
    db.refresh(survey)
    
    return {
        "status": "ok",
        "survey_id": survey.id,
    }


@router.get("/survey/{session_id}")
def get_survey(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get survey response for a session."""
    survey = db.query(SurveyResponse).filter(
        SurveyResponse.session_id == session_id
    ).first()
    
    if not survey:
        raise HTTPException(status_code=404, detail="Survey not found")
    
    return {
        "session_id": survey.session_id,
        "q1_willingness": survey.q1_willingness,
        "q2_reasons": json.loads(survey.q2_reasons),
        "q3_concerns": json.loads(survey.q3_concerns),
        "q4_savings_perception": survey.q4_savings_perception,
    }


@router.get("/impacts/{session_id}")
def get_impacts(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get broader impacts for a session."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get impacts from engine
    impacts = calculation_engine.calculate_impacts(session_id)
    
    return impacts