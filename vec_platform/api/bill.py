"""Bill API endpoints."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from vec_platform.main import get_db, calculation_engine
from vec_platform.models import (
    Session as SessionModel,
    DailyProfile,
    BillBreakdown,
    UserInput,
)

router = APIRouter()


class BillCreate(BaseModel):
    session_id: str
    scenario: str = "no_vec"


class BillResponse(BaseModel):
    id: int
    session_id: str
    scenario: str
    step: int
    energy_purchase: float
    grid_fee: float
    energy_tax: float
    pv_self_consumption: float
    vec_discount: float
    feed_in_income: float
    net_cost: float

    class Config:
        from_attributes = True


@router.post("/bill")
def create_bill(
    data: BillCreate,
    db: Session = Depends(get_db)
):
    """Calculate bill for a session."""
    # Get profile
    profile = db.query(DailyProfile).filter(
        DailyProfile.session_id == data.session_id,
        DailyProfile.step == 2
    ).first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Phase N F6: lookup user_input.area_m2 for the tiered grid fee.
    # Phase H+1: building_type + is_owner gate effekttariff; legacy
    # housing_type + ownership_type are one-cycle fallbacks.
    user_input = (
        db.query(UserInput)
        .filter(UserInput.session_id == data.session_id)
        .order_by(UserInput.id.desc())
        .first()
    )
    area_m2 = user_input.area_m2 if user_input is not None else None
    building_type = (
        getattr(user_input, "building_type", None)
        if user_input is not None else None
    )
    is_owner = (
        getattr(user_input, "is_owner", None)
        if user_input is not None else None
    )
    housing_type = (
        getattr(user_input, "housing_type", None)
        if user_input is not None else None
    )
    ownership_type = user_input.ownership_type if user_input is not None else None

    # Calculate bill
    bill = calculation_engine.calculate_bill(
        profile, data.scenario,
        area_m2=area_m2,
        building_type=building_type,
        is_owner=is_owner,
        housing_type=housing_type,
        ownership_type=ownership_type,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)
    
    return {
        "status": "ok",
        "bill_id": bill.id,
        "net_cost": bill.net_cost,
    }


@router.get("/bill/{session_id}")
def get_bill(
    session_id: str,
    scenario: str = "no_vec",
    db: Session = Depends(get_db)
):
    """Get bill for a session."""
    bill = db.query(BillBreakdown).filter(
        BillBreakdown.session_id == session_id,
        BillBreakdown.scenario == scenario
    ).first()
    
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    
    return {
        "session_id": bill.session_id,
        "scenario": bill.scenario,
        "energy_purchase": bill.energy_purchase,
        "grid_fee": bill.grid_fee,
        "energy_tax": bill.energy_tax,
        "pv_self_consumption": bill.pv_self_consumption,
        "vec_discount": bill.vec_discount,
        "feed_in_income": bill.feed_in_income,
        "net_cost": bill.net_cost,
    }


@router.get("/bill-comparison/{session_id}")
def get_bill_comparison(
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get bill comparison for all scenarios."""
    bills = db.query(BillBreakdown).filter(
        BillBreakdown.session_id == session_id
    ).all()
    
    result = {}
    for bill in bills:
        result[bill.scenario] = {
            "energy_purchase": bill.energy_purchase,
            "grid_fee": bill.grid_fee,
            "energy_tax": bill.energy_tax,
            "pv_self_consumption": bill.pv_self_consumption,
            "vec_discount": bill.vec_discount,
            "feed_in_income": bill.feed_in_income,
            "net_cost": bill.net_cost,
        }
    
    return result