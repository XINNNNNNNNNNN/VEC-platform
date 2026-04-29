"""SQLAlchemy base and models for VEC Platform."""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.sqlite import JSON


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Session(Base):
    """User session tracking."""
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    # Deprecated: stores the v2 building_type. Kept for backward compat
    # until Phase 3.1 reshapes Step 1.
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ----- v3.0 fields -----
    # Multi-country support: country self-selected at Step 8, language stamped
    # at session creation. Defaults keep v2 behaviour (Sweden, English).
    country_code: Mapped[str] = mapped_column(
        String(8), default="SE", server_default="SE", nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(8), default="en", server_default="en", nullable=False,
    )
    # A/B/C arm assigned at session creation (Phase 3 will write A/B; for now
    # the column exists but every session lands in the C control group).
    info_calibration_arm: Mapped[str] = mapped_column(
        String(1), default="C", server_default="C", nullable=False,
    )
    # 'expert' vs 'general' — Phase 3.1 derives this from a Step 1 occupation
    # question. Until then everyone is 'general'.
    expertise: Mapped[str] = mapped_column(
        String(16), default="general", server_default="general", nullable=False,
    )

    # Relationships
    user_input: Mapped[Optional["UserInput"]] = relationship(
        "UserInput", back_populates="session", uselist=False
    )
    daily_profiles: Mapped[list["DailyProfile"]] = relationship(
        "DailyProfile", back_populates="session"
    )
    bill_breakdowns: Mapped[list["BillBreakdown"]] = relationship(
        "BillBreakdown", back_populates="session"
    )
    shadow_prices: Mapped[Optional["ShadowPrices"]] = relationship(
        "ShadowPrices", back_populates="session", uselist=False
    )
    device_shifts: Mapped[list["DeviceShift"]] = relationship(
        "DeviceShift", back_populates="session"
    )
    drag_logs: Mapped[list["DragLog"]] = relationship(
        "DragLog", back_populates="session"
    )
    survey_response: Mapped[Optional["SurveyResponse"]] = relationship(
        "SurveyResponse", back_populates="session", uselist=False
    )


class UserInput(Base):
    """Step 1: User role and building information."""
    __tablename__ = "user_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    area_m2: Mapped[float] = mapped_column(Float)
    people: Mapped[int] = mapped_column(Integer)
    has_ev: Mapped[bool] = mapped_column(Boolean, default=False)
    has_pv: Mapped[bool] = mapped_column(Boolean, default=False)
    pv_kwp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_bess: Mapped[bool] = mapped_column(Boolean, default=False)
    bess_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ----- v3.0 fields -----
    # Replace v2 `building_type` (5-choice) and `heating` with these two.
    # MockEngine derives an internal building_type code from ownership + DER.
    ownership_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'tenant' | 'owner'
    occupation: Mapped[str] = mapped_column(String(64), nullable=False)
    # ^ 'energy_professional' | 'general_public' (Step 1 Q5; drives sessions.expertise)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="user_input")


class DailyProfile(Base):
    """Step 2: 96-slot load curve data."""
    __tablename__ = "daily_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    step: Mapped[int] = mapped_column(Integer)  # 2=baseline, 3=customized, 5=responded
    
    # 96 slots stored as JSON arrays
    rigid_load: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    flexible_load: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    pv_generation: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    net_load: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    
    # Device-level breakdown
    devices: Mapped[str] = mapped_column(Text)  # JSON {device_name: [...]}

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="daily_profiles")


class BillBreakdown(Base):
    """Step 2, 6: Bill calculation breakdown."""
    __tablename__ = "bill_breakdowns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    scenario: Mapped[str] = mapped_column(String(50))  # "no_vec" / "vec_no_adjust" / "vec_adjusted"
    step: Mapped[int] = mapped_column(Integer)
    
    energy_purchase: Mapped[float] = mapped_column(Float)
    grid_fee: Mapped[float] = mapped_column(Float)
    energy_tax: Mapped[float] = mapped_column(Float)
    pv_self_consumption: Mapped[float] = mapped_column(Float)
    vec_discount: Mapped[float] = mapped_column(Float)
    feed_in_income: Mapped[float] = mapped_column(Float)
    net_cost: Mapped[float] = mapped_column(Float)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="bill_breakdowns")


class ShadowPrices(Base):
    """Step 4: VEC internal shadow prices."""
    __tablename__ = "shadow_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    
    retail_price: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    internal_buy: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    internal_sell: Mapped[str] = mapped_column(Text)  # JSON [float x 96]
    feed_in_price: Mapped[str] = mapped_column(Text)  # JSON [float x 96]

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="shadow_prices")


class DeviceShift(Base):
    """Step 3, 5: Final device positions."""
    __tablename__ = "device_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    step: Mapped[int] = mapped_column(Integer)  # 3 or 5
    device_name: Mapped[str] = mapped_column(String(100))
    original_start: Mapped[int] = mapped_column(Integer)
    original_end: Mapped[int] = mapped_column(Integer)
    final_start: Mapped[int] = mapped_column(Integer)
    final_end: Mapped[int] = mapped_column(Integer)
    willing: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    unwilling_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="device_shifts")


class DragLog(Base):
    """Step 3, 5: Every drag operation logged."""
    __tablename__ = "drag_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    step: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    device_name: Mapped[str] = mapped_column(String(100))
    from_start: Mapped[int] = mapped_column(Integer)
    from_end: Mapped[int] = mapped_column(Integer)
    to_start: Mapped[int] = mapped_column(Integer)
    to_end: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(50))  # "move" / "add" / "remove"

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="drag_logs")


class SurveyResponse(Base):
    """Step 8: Final survey responses."""
    __tablename__ = "survey_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))

    q1_willingness: Mapped[str] = mapped_column(String(50))
    q2_reasons: Mapped[str] = mapped_column(Text)  # JSON array
    q3_concerns: Mapped[str] = mapped_column(Text)  # JSON array
    q4_savings_perception: Mapped[str] = mapped_column(String(50))

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="survey_response")


# ==================== v3.0 tables ====================

class PriorExpectation(Base):
    """First and second savings-percentage guesses.

    Phase 3 will write one row at Step 0 (measurement_round=1) and another at
    Step 2 (measurement_round=2) so we can compare expectations before vs.
    after seeing the participant's own load curve.
    """
    __tablename__ = "prior_expectations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True,
    )
    measurement_round: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    pct: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 – 50.0
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False,
    )


class ExitThreshold(Base):
    """Step 8 exit-threshold question (5-choice: 100/75/50/25/0% of stated savings)."""
    __tablename__ = "exit_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"),
        nullable=False, index=True, unique=True,
    )
    threshold_ratio: Mapped[float] = mapped_column(Float, nullable=False)  # ∈ {1.0, 0.75, 0.5, 0.25, 0.0}
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False,
    )


# Import for type hints
from vec_platform.models import Session, UserInput, DailyProfile, BillBreakdown, ShadowPrices, DeviceShift, DragLog, SurveyResponse

__all__ = [
    "Base",
    "Session",
    "UserInput",
    "DailyProfile",
    "BillBreakdown",
    "ShadowPrices",
    "DeviceShift",
    "DragLog",
    "SurveyResponse",
    "PriorExpectation",
    "ExitThreshold",
]