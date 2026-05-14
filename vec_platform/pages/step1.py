"""Step 1 — household profile form + submit callback (v3.0).

Five questions:
  Q1  ownership type        (tenant / owner)
  Q2  DER multi-select      (PV / BESS / EV)
  Q3  area                  (m²)
  Q4  people                (count)
  Q5  occupation            (energy professional / general public)

The legacy v2 questions (4-choice building_type, 3-choice heating) are gone.
MockEngine derives an internal building_type code from ownership + DER, so
the engine still drives the right base-load amplitude.

Importing this module registers the Dash callback against ``dash_app``.
"""

import uuid

from dash import html, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform import config
from vec_platform.runtime import dash_app, SessionLocal, calculation_engine
from vec_platform.pages._helpers import _parse_session_id
# Phase 3.X-fix-10: share the same vec_familiarity threshold step8 uses to
# gate the expert block, so the "are you in the high-familiarity subset?"
# decision lives in exactly one place. step1 hides Q5 (occupation) when
# the user is *below* the gate; step8 shows the expert block when the
# user is *at or above* the gate. Both must pivot on identical values.
from vec_platform.pages.step7 import _EXPERT_FAMILIARITY_GATE


# ==================== Step 1 ====================

# Phase O: 4-way building_type aligned with E.ON Sweden consumer
# survey 2025 categories (Lägenhet / Radhus / Villa-hus / Annat).
# Replaces the Phase E 2-way ownership_type radio. After Sweden's
# 2026 effekttariff mandate was cancelled the engine no longer needs
# an ownership-driven branch, and a 4-way building question is more
# informative for downstream segmentation than the binary rent/own.
_BUILDING_TYPE_OPTIONS = [
    {"label": "Apartment (Lägenhet)", "value": "apartment"},
    {"label": "Townhouse (Radhus)", "value": "townhouse"},
    {"label": "House / villa (Villa/hus)", "value": "house"},
    {"label": "Other (Fritidshus / annat)", "value": "other"},
]

# DEPRECATED Phase E options — kept only for the rollback path. New
# code reads building_type instead. submit_step1 no longer writes
# user_input.ownership_type.
_OWNERSHIP_OPTIONS = [
    {"label": "Tenant (rent)", "value": "tenant"},
    {"label": "Owner", "value": "owner"},
]

_DER_OPTIONS = [
    {"label": "Solar PV", "value": "pv"},
    {"label": "Battery storage (BESS)", "value": "bess"},
    {"label": "Electric vehicle (EV)", "value": "ev"},
]

# Phase 3.X-fix-11: labels reduced to Yes/No after the question itself
# was rephrased into a yes/no form ("Are you an energy-related researcher
# or professional?"). The scope description that used to live inside the
# long label moved into a P subtitle next to the H5. Values are preserved
# verbatim ('energy_professional' / 'general_public') so submit_step1's
# expertise derivation (line ~217) and any pre-fix-11 rows in
# user_inputs.occupation stay 1:1 compatible.
_OCCUPATION_OPTIONS = [
    {"label": "Yes", "value": "energy_professional"},
    {"label": "No",  "value": "general_public"},
]


def step1_layout(session_id: str | None = None):
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light", className="py-2 small")
        if session_id else
        dbc.Alert("No active session — open the site from '/' to create one.",
                  color="warning", className="py-2 small")
    )

    # Phase 3.X-fix-10: Q5 (occupation / "energy professional?") is only
    # asked of participants whose Step 0 vec_familiarity is in the top 2
    # of the 5-pt scale. Users below the gate are extremely unlikely to
    # be energy professionals, so the question is information-redundant
    # for them — and hiding it removes a small surface for the demand
    # effect. The high-familiarity subset is still asked, preserving the
    # backward-compat comparison with the legacy expertise self-label.
    show_occupation = False
    # Phase F: if the participant is editing Step 1 after having
    # generated any downstream data (customize / respond / survey
    # rows), warn them up-front that pressing Next will wipe that
    # later progress. Same detection predicate as submit_step1's
    # cascade-delete trigger.
    has_downstream = False
    if session_id:
        from vec_platform.models import (
            Session as SessionModel,
            DailyProfile,
            DeviceShift,
            DragLog,
            SurveyResponse,
        )
        db = SessionLocal()
        try:
            sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            vec_fam = sess.vec_familiarity if sess else None
            has_downstream = (
                db.query(DailyProfile)
                .filter(
                    DailyProfile.session_id == session_id,
                    DailyProfile.step.in_((3, 5)),
                )
                .first() is not None
                or db.query(DeviceShift).filter_by(session_id=session_id).first() is not None
                or db.query(DragLog).filter_by(session_id=session_id).first() is not None
                or db.query(SurveyResponse).filter_by(session_id=session_id).first() is not None
            )
        finally:
            db.close()
        show_occupation = vec_fam in _EXPERT_FAMILIARITY_GATE

    # Phase 3.X-fix-14: the Q5 block is *always* rendered into the DOM,
    # but the wrapper html.Div is CSS-hidden (display:none) for the
    # low-familiarity subset. Earlier (fix-10) the block was conditionally
    # appended; that caused submit_step1's State("occupation", "value")
    # to reference a missing component and Dash strict-mode raised a
    # ReferenceError, leaving Step 1 stuck on Next for low-familiarity
    # sessions. Always-in-DOM + CSS visibility keeps the callback graph
    # valid; fix-13's 'general_public' default value means the hidden
    # widget reports a truthy value to submit_step1 so validation passes.
    occupation_block = html.Div(
        [
            # Q5: Occupation (drives sessions.expertise; rephrased as a
            # yes/no question post fix-11 with the scope description in
            # a subtitle).
            html.H5("Q5 · Are you an energy-related researcher or professional?"),
            html.P(
                "(works/studies in energy industry, utilities, energy "
                "research, or energy policy)",
                className="text-muted small",
            ),
            dbc.RadioItems(
                id="occupation",
                options=_OCCUPATION_OPTIONS,
                # Phase 3.X-fix-15: no default value — high-familiarity
                # participants must actively pick Yes/No so the answer
                # carries real intent (a default would silently classify
                # passive participants and pollute the data semantic).
                # Low-familiarity participants don't see Q5 at all
                # (fix-14 hides the wrapper Div with display:none) and
                # their occupation State arrives at submit as None;
                # submit_step1's fix-10 conditional-required check skips
                # that validation when vec_familiarity is below the gate,
                # so None-occupation low-fam users still pass Next.
                value=None,
                className="mb-2",
            ),
            # Phase O-fix-10: per-Q hint div for the occupation question.
            # Lives inside the occupation_block so it disappears with
            # the rest of Q5 when the block is CSS-hidden for low
            # vec_familiarity participants.
            html.Div(id="q5-hint", className="step1-hint-text mb-3"),
        ],
        style={} if show_occupation else {"display": "none"},
    )

    # Phase F: warn the participant before they overwrite progress
    # made in later steps.
    cascade_warning = (
        dbc.Alert(
            [
                html.Strong("Heads up: "),
                "you have answers saved in later steps. Pressing "
                "“Next → Generate my profile” will reset your customize, "
                "respond, and survey progress so the rest of the flow "
                "matches whatever you change here.",
            ],
            color="warning",
            className="py-2 small",
        )
        if has_downstream else None
    )

    return html.Div([
        html.H2("Step 1: Tell us about your home"),
        html.P("A few quick questions so we can build your typical electricity day."),

        session_note,
        cascade_warning,

        dbc.Card([
            dbc.CardBody([
                # Q1: Building type (Phase O — 4-way replacing the
                # legacy 2-way ownership_type radio). Mirrors the
                # E.ON Sweden consumer survey 2025 categories.
                html.H5("Q1 · What kind of home do you live in?"),
                dbc.RadioItems(
                    id="building-type",
                    options=_BUILDING_TYPE_OPTIONS,
                    value=None,
                    className="mb-2",
                ),
                # Phase O-fix-10: per-Q hint div. Always rendered (Dash
                # needs the component present in the layout to wire
                # the callback). Populated only when the user submits
                # with this question unanswered; cleared by the per-Q
                # hint-clear callback when the user picks a value.
                html.Div(id="q1-hint", className="step1-hint-text mb-4"),

                # Q2: DER (multi-select, may be empty)
                html.H5("Q2 · Which of these do you have at home? "
                        "(select all that apply)"),
                dbc.Checklist(
                    id="der-options",
                    options=_DER_OPTIONS,
                    value=[],
                    className="mb-4",
                ),

                # Q3: Area (Phase O-fix-10: 20-500 m² covers a studio
                # at the low end and a large multi-generation villa at
                # the high end. Range shown inline so participants know
                # the supported window before submitting.)
                html.H5(
                    f"Q3 · Approximate floor area of your home "
                    f"({int(config.AREA_MIN_M2)}–{int(config.AREA_MAX_M2)} m²)"
                ),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(
                            id="area", type="number", value=75,
                            min=config.AREA_MIN_M2,
                            max=config.AREA_MAX_M2,
                        ),
                        width=4,
                    ),
                ], className="mb-2"),
                html.Div(id="q3-hint", className="step1-hint-text mb-4"),

                # Q4: People (Phase O-fix-10: 1-10 covers single-person
                # households up to multi-generation extended families.)
                html.H5(
                    f"Q4 · Number of people living in your home "
                    f"({config.PEOPLE_MIN}–{config.PEOPLE_MAX})"
                ),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(
                            id="people", type="number", value=2,
                            min=config.PEOPLE_MIN,
                            max=config.PEOPLE_MAX,
                        ),
                        width=4,
                    ),
                ], className="mb-2"),
                html.Div(id="q4-hint", className="step1-hint-text mb-4"),

                occupation_block,

                html.Hr(),
                # Phase O-fix-10: Next button uses CSS .disabled-look
                # (gray + not-allowed cursor) rather than the HTML
                # `disabled` attribute. Disabled HTML buttons don't
                # fire click events, so we couldn't surface per-Q
                # hints from a click while keeping a disabled visual.
                # By styling only — never setting the prop — the
                # button stays clickable and submit_step1 can validate
                # + populate the hint divs. The step1-error central
                # banner is gone; per-Q hints replace it.
                dbc.Button(
                    "Next → Generate my profile",
                    id="btn-next-step1",
                    color="primary",
                    size="lg",
                    className="mt-2 disabled-look",
                    n_clicks=0,
                ),
            ])
        ]),
    ])


# ==================== Step 1 validation (Phase O-fix-10) ============
# Returns {hint_id: message} for every question that fails validation.
# Empty dict = all valid. Used by both:
#   - update_next_visual (drives the Next button's className gray/blue)
#   - submit_step1       (populates per-Q hint divs on submit click)
# Keeping the predicate in one place stops the two callbacks drifting.
def _validate_step1(building_type, area, people, occupation,
                    occupation_required):
    """Return {hint_div_id: message} for invalid answers.

    ``der_options`` (Q2) is intentionally *not* validated — a household
    may legitimately own none of PV/BESS/EV, and the checklist's empty
    state is meaningful data, not a missing answer.

    Range checks for Q3/Q4 use the bounds defined in config (Phase
    O-fix-10 expansion: 20-500 m² and 1-10 people). Strings or NaN
    coming through Dash's dbc.Input(type='number') are treated as
    missing — defensive against synthetic submissions.
    """
    hints = {}

    if not building_type:
        hints["q1-hint"] = "⚠ Please answer this question."

    # Q3 area.
    if area is None or area == "":
        hints["q3-hint"] = "⚠ Please enter your home size."
    else:
        try:
            a = float(area)
            if a != a:  # NaN
                raise ValueError
        except (TypeError, ValueError):
            hints["q3-hint"] = "⚠ Please enter a number."
        else:
            if a < config.AREA_MIN_M2 or a > config.AREA_MAX_M2:
                hints["q3-hint"] = (
                    f"⚠ Must be between {int(config.AREA_MIN_M2)} "
                    f"and {int(config.AREA_MAX_M2)} m² "
                    f"(you entered {a:g})."
                )

    # Q4 people.
    if people is None or people == "":
        hints["q4-hint"] = "⚠ Please enter how many people live in your home."
    else:
        try:
            p = float(people)
            if p != p:  # NaN
                raise ValueError
        except (TypeError, ValueError):
            hints["q4-hint"] = "⚠ Please enter a number."
        else:
            if p < config.PEOPLE_MIN or p > config.PEOPLE_MAX:
                hints["q4-hint"] = (
                    f"⚠ Must be between {config.PEOPLE_MIN} "
                    f"and {config.PEOPLE_MAX} "
                    f"(you entered {int(p) if p.is_integer() else p:g})."
                )

    # Q5 only when the participant's vec_familiarity places them in
    # the expert gate. Low-fam users don't see the question; we must
    # not flag them as failing it.
    if occupation_required and not occupation:
        hints["q5-hint"] = "⚠ Please answer this question."

    return hints


def _occupation_required(session_id):
    """Lookup-helper: does this session require the Q5 answer?

    Mirrors the gate used by step1_layout's `show_occupation` so the
    visual rendering and the validation pivot on identical state.
    """
    if not session_id:
        return False
    from vec_platform.models import Session as SessionModel
    _db = SessionLocal()
    try:
        _sess = (
            _db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .first()
        )
        return (
            _sess is not None
            and _sess.vec_familiarity in _EXPERT_FAMILIARITY_GATE
        )
    finally:
        _db.close()


# ==================== Step 1 Next-button visual callback ============
# Phase O-fix-10: drives the Next button's className based on whether
# all required questions are answered. We deliberately do NOT use the
# `disabled` prop — an HTML disabled button doesn't fire click events,
# which would mean a user clicking it never sees the per-Q hint
# feedback they need to understand why Next isn't working.
#
# Returned classes:
#   - all valid:  "mt-2"                — Bootstrap's btn-primary
#                                          color (set by dbc.Button
#                                          color='primary') comes
#                                          through; button looks active.
#   - any error:  "mt-2 disabled-look"  — .disabled-look CSS rule
#                                          forces gray background +
#                                          not-allowed cursor while
#                                          leaving click events alive.
@dash_app.callback(
    Output("btn-next-step1", "className"),
    Input("building-type", "value"),
    Input("area", "value"),
    Input("people", "value"),
    Input("occupation", "value"),
    Input("url", "search"),
)
def update_next_visual(building_type, area, people, occupation, search):
    session_id = _parse_session_id(search)
    occ_required = _occupation_required(session_id)
    hints = _validate_step1(building_type, area, people, occupation,
                            occ_required)
    if hints:
        return "mt-2 disabled-look"
    return "mt-2"


# ==================== Step 1 per-Q hint-clear callbacks =============
# Phase O-fix-10: when the participant edits an input, immediately wipe
# the matching hint so the page stops scolding them while they're
# fixing it. Output collisions with submit_step1's hint Outputs are
# resolved via Dash's allow_duplicate=True (requires Dash >= 2.9; the
# project uses Dash 4.1+). prevent_initial_call avoids wiping hints
# that submit_step1 just rendered.
@dash_app.callback(
    Output("q1-hint", "children", allow_duplicate=True),
    Input("building-type", "value"),
    prevent_initial_call=True,
)
def _clear_q1_hint(_value):
    return ""


@dash_app.callback(
    Output("q3-hint", "children", allow_duplicate=True),
    Input("area", "value"),
    prevent_initial_call=True,
)
def _clear_q3_hint(_value):
    return ""


@dash_app.callback(
    Output("q4-hint", "children", allow_duplicate=True),
    Input("people", "value"),
    prevent_initial_call=True,
)
def _clear_q4_hint(_value):
    return ""


@dash_app.callback(
    Output("q5-hint", "children", allow_duplicate=True),
    Input("occupation", "value"),
    prevent_initial_call=True,
)
def _clear_q5_hint(_value):
    return ""


# ==================== Step 1 submit callback ====================
# Default sizing for derived DER properties — keeps the v2 MockEngine
# behaviour (5 kWp PV ≈ 3 kW noon peak, 10 kWh battery).
_DEFAULT_PV_KWP = 5.0
_DEFAULT_BESS_KWH = 10.0
_SCENARIOS = ("no_vec", "vec_no_adjust", "vec_adjusted")


@dash_app.callback(
    Output("url", "pathname"),
    Output("url", "search"),
    # Phase O-fix-10: per-Q hint Outputs. allow_duplicate not needed
    # here because this callback is the canonical writer; the per-Q
    # clear callbacks declare allow_duplicate on their copies of
    # these Outputs.
    Output("q1-hint", "children"),
    Output("q3-hint", "children"),
    Output("q4-hint", "children"),
    Output("q5-hint", "children"),
    Input("btn-next-step1", "n_clicks"),
    State("building-type", "value"),
    State("der-options", "value"),
    State("area", "value"),
    State("people", "value"),
    State("occupation", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step1(n_clicks, building_type, der_options, area, people,
                 occupation, search):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update, no_update

    from vec_platform.models import Session as SessionModel, UserInput

    # Phase O-fix-10: validate every required answer up-front and
    # populate per-Q hint divs. The validate helper is the same one
    # update_next_visual uses, so visual disable-look and submit-time
    # rejection are guaranteed to agree.
    session_id = _parse_session_id(search)
    occ_required = _occupation_required(session_id)
    hints = _validate_step1(building_type, area, people, occupation,
                            occ_required)
    if hints:
        return (
            no_update, no_update,
            hints.get("q1-hint", ""),
            hints.get("q3-hint", ""),
            hints.get("q4-hint", ""),
            hints.get("q5-hint", ""),
        )

    # All required answers valid. Adopt the canonical numeric form so
    # the DB write below operates on a float / int.
    area = float(area)
    people = int(float(people))

    der = der_options or []
    has_pv = "pv" in der
    has_bess = "bess" in der
    has_ev = "ev" in der
    # fix-10: derive expertise only when occupation was actually asked.
    # When the question was hidden (low vec_familiarity), expertise stays
    # NULL on the session row to mirror the "not asked" data semantics.
    if occupation == "energy_professional":
        expertise = "expert"
    elif occupation == "general_public":
        expertise = "general"
    else:
        expertise = None  # widget hidden or never answered

    # Phase E: upsert pattern. Pressing Back and resubmitting Step 1
    # used to produce a fresh row in user_inputs + daily_profiles
    # (step=2) + 3 rows in bill_breakdowns; now we update the existing
    # row in place. Phase C calibration fields (pv_kwp, bess_kwh,
    # ev_kwh, load_scale_factor, *_calibrated) are preserved across
    # resubmits as long as the matching has_X selection is unchanged;
    # flipping has_X resets the corresponding capacity to its default
    # so a participant who unchecks PV doesn't leave a stale 15 kWp.
    from vec_platform.models import (
        Session as SessionModel,
        UserInput,
        DailyProfile,
        BillBreakdown,
        DeviceShift,
        DragLog,
        SurveyResponse,
        ShadowPrices,
        PriorExpectation,
        WillingnessMeasurement,
        ExitThreshold,
    )

    db = SessionLocal()
    try:
        if session_id:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        else:
            session = None

        if session is None:
            session_id = str(uuid.uuid4())
            session = SessionModel(id=session_id, current_step=1)
            db.add(session)
            db.flush()

        # v3: drives Step 8's expert-only follow-ups (fix-9 actually moved
        # that gate to vec_familiarity; expertise stays for backward-
        # compat analysis).
        if expertise is not None:
            session.expertise = expertise
        # else: leave existing value (None for fresh sessions; whatever
        # was there for a re-submit). Don't overwrite with None.

        # Phase F: detect downstream data left over from an earlier
        # walk-through. "Downstream" = anything produced after the
        # baseline step=2 profile: step=3/5 daily_profiles + bill rows,
        # device_shifts, drag_logs, shadow_prices, survey_responses,
        # plus the round=2 prior-expectation, round=2/3 willingness
        # measurements, and exit_thresholds. The round=1 measurements
        # are taken *before* Step 1 (welcome page + info-calibration
        # arm) and are explicitly preserved.
        has_downstream = (
            db.query(DailyProfile)
            .filter(
                DailyProfile.session_id == session_id,
                DailyProfile.step.in_((3, 5)),
            )
            .first() is not None
            or db.query(DeviceShift).filter_by(session_id=session_id).first() is not None
            or db.query(DragLog).filter_by(session_id=session_id).first() is not None
            or db.query(SurveyResponse).filter_by(session_id=session_id).first() is not None
        )

        # ---- UserInput upsert ----
        # Snapshot the previous has_X state *before* we mutate the row so
        # we can decide whether each DER capacity needs to be reset to
        # its default (DER added or removed) or preserved (selection
        # unchanged — Phase C calibration stays put).
        existing_ui = (
            db.query(UserInput)
            .filter(UserInput.session_id == session_id)
            .first()
        )
        prev_has_pv = existing_ui.has_pv if existing_ui is not None else None
        prev_has_bess = existing_ui.has_bess if existing_ui is not None else None
        prev_has_ev = existing_ui.has_ev if existing_ui is not None else None

        if existing_ui is None:
            user_input = UserInput(session_id=session_id)
            db.add(user_input)
        else:
            user_input = existing_ui

        # Step 1's own fields always reflect the latest submit.
        # Phase O: write building_type (the new authoritative column).
        # ownership_type is no longer written — the column was relaxed
        # to nullable in alembic fea15d1b9cf2 and stays NULL for new
        # rows. Older rows (pre-Phase-O) keep their existing values
        # via the upsert path (the line below is not in this branch).
        user_input.building_type = building_type
        user_input.occupation = occupation
        user_input.area_m2 = float(area)
        user_input.people = int(people)
        user_input.has_pv = has_pv
        user_input.has_bess = has_bess
        user_input.has_ev = has_ev

        # DER capacity defaults: only touch when has_X transitions or on
        # first-time creation. Otherwise leave Phase C calibration alone.
        if prev_has_pv is None:
            # First-time row — seed defaults the same way pre-Phase E did.
            user_input.pv_kwp = _DEFAULT_PV_KWP if has_pv else None
        elif prev_has_pv != has_pv:
            user_input.pv_kwp = _DEFAULT_PV_KWP if has_pv else None
            user_input.pv_calibrated = False

        if prev_has_bess is None:
            user_input.bess_kwh = _DEFAULT_BESS_KWH if has_bess else None
        elif prev_has_bess != has_bess:
            user_input.bess_kwh = _DEFAULT_BESS_KWH if has_bess else None
            user_input.bess_calibrated = False

        # ev_kwh has no Step 1 default (column was nullable from the
        # start; UI defaults to 60 client-side). On a fresh row leave it
        # NULL; on a has_ev flip clear the calibrated flag so the
        # calibration panel re-prompts.
        if prev_has_ev is not None and prev_has_ev != has_ev:
            user_input.ev_kwh = None
            user_input.ev_calibrated = False

        db.flush()

        # ---- DailyProfile + BillBreakdown step=2 are recomputed ----
        # The step=2 baseline is a derived view of user_input — the
        # simplest correct behaviour on resubmit is to drop the old
        # rows and write fresh ones from the updated user_input.
        db.query(BillBreakdown).filter(
            BillBreakdown.session_id == session_id,
            BillBreakdown.step == 2,
        ).delete(synchronize_session=False)
        db.query(DailyProfile).filter(
            DailyProfile.session_id == session_id,
            DailyProfile.step == 2,
        ).delete(synchronize_session=False)

        # Phase F: cascade-delete any downstream data so it can't
        # diverge from the new baseline. Without this, a participant
        # who pressed Back after finishing the survey would leave
        # daily_profiles(step=3/5), device_shifts, etc. populated from
        # the previous ui state -- making the persisted "what you
        # customised" rows incompatible with the new step=2 baseline.
        # We DO NOT touch prior_expectations(round=1) or
        # willingness_measurements(round=1) because those are
        # collected before Step 1 (welcome page / info-calibration
        # arm) and remain valid baseline measurements regardless of
        # how the participant subsequently edits Step 1.
        if has_downstream:
            db.query(BillBreakdown).filter(
                BillBreakdown.session_id == session_id,
                BillBreakdown.step.in_((3, 5)),
            ).delete(synchronize_session=False)
            db.query(DailyProfile).filter(
                DailyProfile.session_id == session_id,
                DailyProfile.step.in_((3, 5)),
            ).delete(synchronize_session=False)
            db.query(DeviceShift).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            db.query(DragLog).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            db.query(SurveyResponse).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            db.query(ShadowPrices).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            db.query(PriorExpectation).filter(
                PriorExpectation.session_id == session_id,
                PriorExpectation.measurement_round == 2,
            ).delete(synchronize_session=False)
            db.query(WillingnessMeasurement).filter(
                WillingnessMeasurement.session_id == session_id,
                WillingnessMeasurement.round.in_((2, 3)),
            ).delete(synchronize_session=False)
            db.query(ExitThreshold).filter_by(session_id=session_id).delete(
                synchronize_session=False
            )
            # The participant is no longer in a "finished" state; they
            # have invalidated all their later answers.
            session.completed = False
            # current_step also goes back to the customize entry point
            # (matches the post-cascade reality: they have to redo
            # everything past Step 1).
            session.current_step = 2
        else:
            # Phase F Q1: when no downstream exists, current_step is
            # only nudged forward to 2, never back. This preserves
            # progress when the participant idly resubmits Step 1
            # before they've actually gone anywhere later.
            if session.current_step is None or session.current_step < 2:
                session.current_step = 2

        db.flush()

        profile = calculation_engine.generate_profile(user_input)
        db.add(profile)
        db.flush()

        for scenario in _SCENARIOS:
            # Phase N F6: pass area_m2 so grid_fee uses the tiered
            # nätavgift structure instead of the deprecated flat 580.
            # Phase O: pass building_type for the 2-archetype split.
            # ownership_type intentionally NOT passed — effekttariff
            # removed; mock.calculate_bill still accepts the kwarg
            # for compat but ignores it.
            db.add(calculation_engine.calculate_bill(
                profile, scenario,
                area_m2=user_input.area_m2,
                building_type=user_input.building_type,
            ))

        db.commit()
    finally:
        db.close()

    # Phase O: all participants go directly to /dash/info_calibration.
    # The tenant disclaimer branch (formerly routed renters through a
    # warning page) is dropped because Step 1 no longer asks ownership.
    # The /dash/tenant_disclaimer page is still mounted by main.py for
    # any rollback flow that wants to re-enable it.
    next_path = "/dash/info_calibration"
    # Phase O-fix-10: clear every hint on the success path (defensive —
    # the per-Q clear callbacks already wipe them as the participant
    # corrected each field, but a synthetic click that bypasses the
    # input events would otherwise leave stale text behind).
    return next_path, f"?session_id={session_id}", "", "", "", ""
