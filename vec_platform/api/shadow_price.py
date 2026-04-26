"""Shadow price API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vec_platform.main import get_db, calculation_engine
from vec_platform.models import Session as SessionModel, ShadowPrices

router = APIRouter()


@router.get("/shadow-prices/{session_id}")
def get_shadow_prices(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get shadow prices for a session."""
    # Check session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get or create shadow prices
    shadow = db.query(ShadowPrices).filter(
        ShadowPrices.session_id == session_id
    ).first()
    
    if not shadow:
        # Generate new shadow prices
        shadow = calculation_engine.get_shadow_prices(session_id)
        db.add(shadow)
        db.commit()
        db.refresh(shadow)
    
    return {
        "session_id": shadow.session_id,
        "retail_price": json.loads(shadow.retail_price),
        "internal_buy": json.loads(shadow.internal_buy),
        "internal_sell": json.loads(shadow.internal_sell),
        "feed_in_price": json.loads(shadow.feed_in_price),
    }