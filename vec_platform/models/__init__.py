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
    # Multi-country support: country self-selected at the final survey
    # (Step 7 in the Phase 4-A 7-step flow, formerly Step 8); language
    # stamped
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

    # v3.X-fix-7 — E.ON Q9 alignment. 5-point self-rated familiarity with
    # the VEC concept, asked at Step 0 *before* the first prior-expectation
    # slider so it serves as a baseline covariate for the info-calibration
    # A/B/C arm analysis. Values: 'never_heard' / 'heard_no_understand' /
    # 'somewhat_familiar' / 'very_familiar' / 'have_participated'.
    vec_familiarity: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
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
    # Phase C reuses pv_kwp / bess_kwh as the canonical user-edited
    # capacity values (rather than adding pv_kw / bess_kwh_v2). pv_kwp
    # is already load-bearing — engine/mock.py reads it as the PV
    # peak — so user calibrations propagate to the bill via the
    # existing recalculate path.
    pv_kwp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    has_bess: Mapped[bool] = mapped_column(Boolean, default=False)
    bess_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Phase C: EV battery capacity (kWh). NULL = "I don't know" / not
    # yet calibrated; UI defaults to 60 kWh when displaying.
    ev_kwh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Phase C: persisted ±5% baseline scaling. Defaults to 1.0 (no
    # scaling). The fix-18 recalculate path still reads scale_factor
    # off the JS `state.scaleFactor` directly; Phase D will swap to
    # this column as source of truth.
    load_scale_factor: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, server_default="1.0",
    )
    # Phase C: research-signal flags. True when the participant
    # actively confirmed the matching capacity (unchecked
    # "I don't know"); False (default) when they accepted the
    # platform default. Pilot analysis can split users by whether
    # they internalised their own situation vs. defaulted.
    pv_calibrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False,
    )
    bess_calibrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False,
    )
    ev_calibrated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", default=False,
    )

    # ----- v3.0 fields -----
    # Replace v2 `building_type` (5-choice) and `heating` with these two.
    # MockEngine derives an internal building_type code from ownership + DER.
    ownership_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'tenant' | 'owner'
    # Step 1 Q5; drives sessions.expertise. Phase 3.X-fix-10 relaxed
    # this to nullable: Q5 is conditionally rendered (only when
    # vec_familiarity is in the top 2 of the 5-pt scale), so users
    # below the gate write NULL here.
    occupation: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # ^ 'energy_professional' | 'general_public' | NULL (not asked)

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="user_input")


class DailyProfile(Base):
    """96-slot load curve data. Phase 4-A preserves the ``step`` value
    semantics (2=baseline, 3=customized, 5=responded) regardless of
    the UI flow renumbering."""
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
    """Bill calculation breakdown. Written by the engine when a profile
    is created (data step=2 baseline) or recalculated after the user
    customises devices (data step=3) or responds to prices (data
    step=5). Read by the comparison page (Step 5 in the Phase 4-A
    7-step flow, formerly Step 6)."""
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
    """VEC internal shadow prices. Created lazily on first visit to the
    prices page (Step 3 in the Phase 4-A 7-step flow, formerly Step 4),
    or earlier if the customize page (Step 2) prefetched them for the
    BESS placeholder track."""
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
    """Final device positions. Written from the customize page (data
    step=3) and the respond page (data step=5). Phase 4-A preserves
    these data step values regardless of UI flow renumbering."""
    __tablename__ = "device_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))
    step: Mapped[int] = mapped_column(Integer)  # 3 (customize) or 5 (respond) — data tags
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
    """Every drag operation logged. Written from the customize page
    (data step=3) and the respond page (data step=5)."""
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
    """Per-session survey row, filled across multiple page submissions.

    Phase 4-A renamed columns step4_* → step3_*, step5_* → step4_*,
    step6_* → step5_*, step7_* → step6_* to match the 7-step flow.
    Step 3 (prices) inserts a row with the two ``step3_*`` fields (and
    NULLs for everything else); Step 7 (final survey) then UPSERTs to
    fill q1-q4. Hence q1-q4 must be nullable — they're populated later
    in the flow than the row's creation. Each session has at most one
    row (enforced by the upsert pattern in
    pages/_survey_helpers.get_or_create_survey_row).
    """
    __tablename__ = "survey_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"))

    # v3.5: relaxed to nullable so the Step 3 prices page can create the
    # row before the Step 7 survey fills these in. Validation at the
    # page layer still requires q1 and q4 before submit fires.
    q1_willingness: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    q2_reasons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    q3_concerns: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    q4_savings_perception: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # v3.5 — Step 3 prices-page selection answers (renamed from step4_*
    # in Phase 4-A).
    step3_q1_shift_intent: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'yes' / 'maybe' / 'no'
    step3_q2_control_pref: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'manual' / 'recommend' / 'auto'

    # v3.6 — Step 4 respond-page counterfactual + perceived effort
    # follow-ups (renamed from step5_* in Phase 4-A). Asked after the
    # participant has dragged devices in response to shadow prices;
    # piggybacked on the first device-shift POST.
    step4_q1_counterfactual: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'yes' / 'no' / 'maybe'
    step4_q2_effort: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'easy' / 'acceptable' / 'disruptive' / 'none'

    # v3.7 — Step 5 compare-page disappointment Likert (renamed from
    # step6_* in Phase 4-A). 1=much less than expected .. 5=much more.
    # The companion 5-point "would you consider joining?" Likert lives
    # in willingness_measurements with round=2 (kept in that table to
    # keep all three willingness measurements — info_calibration /
    # Step 5 / Step 7 — uniform).
    step5_expectation_vs_reality: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    # v3.8 — Step 6 impacts-page broader-impacts shift Likert (renamed
    # from step7_* in Phase 4-A). "Now that you've seen the policy /
    # grid / environment tabs, has this changed your view about joining
    # a VEC?" 1=much less interested .. 5=much more.
    step6_broader_impacts_shift: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )

    # v3.9 — final-survey expansion (Step 7 in the Phase 4-A 7-step
    # flow, formerly Step 8): 3 new survey questions + 3 expert-only
    # questions + 3 demographics fields. All nullable: experts get the
    # expert_* trio asked, non-experts leave them NULL; demographics are
    # asked of everyone but country defaults at submit time.
    q5_trust_source: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )  # 'government' / 'utility' / 'coop' / 'tech' / 'none'
    q6_fairness_pref: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'equal' / 'proportional' / 'needs' / 'unsure'
    q7_transparency_pref: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'minimal' / 'summary' / 'detailed' / 'full'
    expert_q1_realism: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
    )  # 1..5 (very unrealistic .. very realistic)
    expert_q2_barrier: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True,
    )  # 'regulatory' / 'awareness' / 'tech' / 'incentives' / 'biz_model'
    expert_q3_comment: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True,
    )  # free-form, max 200 chars enforced client-side
    demo_age_range: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True,
    )  # '18-29' / '30-39' / '40-49' / '50-59' / '60-69' / '70+'
    demo_gender: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True,
    )  # 'male' / 'female' / 'other' / 'no_answer'
    demo_country: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True,
    )  # ISO-2 country code; defaults to 'SE' at submit time

    # v3.X-fix-7 / fix-8 — E.ON alignment.
    #   drivers_top3: E.ON Q13, max-3 multi-select stored as a JSON list.
    #     Allowed values: 'climate' / 'simplicity' / 'privacy' / 'savings'
    #     / 'transparency' / 'grid_benefit' / 'control' / 'community' /
    #     'other'. fix-8 merged the legacy Q2_reasons question into this
    #     field — the 9 values keep E.ON Q13 cross-reference, but the
    #     final-survey layout shows them under the conversational Q2
    #     wording ("top reasons to join"). q2_reasons column kept as an
    #     escape hatch for the legacy /api/survey endpoint but is no
    #     longer written by the final-survey submit handler.
    #
    # fairness_likert (E.ON Q11) was added in fix-7 and dropped in fix-8
    # (overlap with q6_fairness_pref + no clean placement on the impacts
    # page).
    drivers_top3: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True,
    )

    # Relationship
    session: Mapped["Session"] = relationship("Session", back_populates="survey_response")


# ==================== v3.0 tables ====================

class PriorExpectation(Base):
    """First and second savings-percentage guesses.

    measurement_round=1 is written at Step 0 (welcome / consent page);
    measurement_round=2 is written at the customize page (Step 2 in the
    Phase 4-A 7-step flow, formerly Step 3) on the first device-shift
    POST piggyback. Comparing rounds tells us how expectations move
    once the participant sees their own customised schedule.
    """
    __tablename__ = "prior_expectations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True,
    )
    measurement_round: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    pct: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0 – 50.0
    # 5-point confidence Likert, only collected at round=2 (the
    # customize page, Step 2 in the 7-step flow). NULL for round=1
    # rows from Step 0.
    confidence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False,
    )


class ExitThreshold(Base):
    """Final-survey exit-threshold question (Step 7 in the Phase 4-A
    7-step flow, formerly Step 8). 5-choice: 100/75/50/25/0% of stated
    savings."""
    __tablename__ = "exit_thresholds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"),
        nullable=False, index=True, unique=True,
    )
    threshold_ratio: Mapped[float] = mapped_column(Float, nullable=False)  # ∈ {1.0, 0.75, 0.5, 0.25, 0.0}
    # v3.9 — joining-side counterpart to threshold_ratio: minimum %
    # savings the participant would require *to join in the first place*.
    # 0..50 inclusive. Nullable so existing rows from earlier phases
    # (and any partial future inserts) don't break.
    entry_threshold_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False,
    )


class WillingnessMeasurement(Base):
    """Three measurements of willingness across the journey.

    Phase 4-A flow positions (formerly Step 6 / Step 8 → now Step 5 /
    Step 7):

    round=1 — info-calibration page, 7-point Likert ("how interested
              are you in joining?")
    round=2 — Step 5 compare page (after seeing the bill comparison),
              5-point Likert ("would you actually consider joining?")
    round=3 — Step 7 final survey (final acceptance), 4-point scale

    Phase 3.2b's first write was the round=1 row; the other rounds
    land later in the journey.
    """
    __tablename__ = "willingness_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 | 2 | 3
    scale_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # ^ '7point_interest' | '5point_consider' | '4point_accept'
    value: Mapped[int] = mapped_column(Integer, nullable=False)
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
    "WillingnessMeasurement",
]