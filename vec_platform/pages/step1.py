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

from vec_platform.runtime import dash_app, SessionLocal, calculation_engine
from vec_platform.pages._helpers import _parse_session_id
# Phase 3.X-fix-10: share the same vec_familiarity threshold step8 uses to
# gate the expert block, so the "are you in the high-familiarity subset?"
# decision lives in exactly one place. step1 hides Q5 (occupation) when
# the user is *below* the gate; step8 shows the expert block when the
# user is *at or above* the gate. Both must pivot on identical values.
from vec_platform.pages.step7 import _EXPERT_FAMILIARITY_GATE


# ==================== Step 1 ====================

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
    if session_id:
        from vec_platform.models import Session as SessionModel
        db = SessionLocal()
        try:
            sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            vec_fam = sess.vec_familiarity if sess else None
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
                className="mb-3",
            ),
        ],
        style={} if show_occupation else {"display": "none"},
    )

    return html.Div([
        html.H2("Step 1: Tell us about your home"),
        html.P("A few quick questions so we can build your typical electricity day."),

        session_note,

        dbc.Card([
            dbc.CardBody([
                # Q1: Ownership type
                html.H5("Q1 · Are you a tenant or an owner?"),
                dbc.RadioItems(
                    id="ownership-type",
                    options=_OWNERSHIP_OPTIONS,
                    value=None,
                    className="mb-4",
                ),

                # Q2: DER (multi-select, may be empty)
                html.H5("Q2 · Which of these do you have at home? "
                        "(select all that apply)"),
                dbc.Checklist(
                    id="der-options",
                    options=_DER_OPTIONS,
                    value=[],
                    className="mb-4",
                ),

                # Q3: Area
                html.H5("Q3 · Approximate floor area of your home (m²)"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="area", type="number", value=75, min=30, max=300),
                        width=4,
                    ),
                ], className="mb-4"),

                # Q4: People
                html.H5("Q4 · Number of people living in your home"),
                dbc.Row([
                    dbc.Col(
                        dbc.Input(id="people", type="number", value=2, min=1, max=6),
                        width=4,
                    ),
                ], className="mb-4"),

                occupation_block,

                html.Hr(),
                html.Div(id="step1-error", className="text-danger mb-2"),
                dbc.Button("Next → Generate my profile", id="btn-next-step1",
                          color="primary", size="lg", className="mt-2",
                          # Phase 3.X-fix-16: starts disabled; toggle_step1_next
                          # callback enables when all required fields are filled
                          # (matches the disable-toggle pattern used on Steps 3-8).
                          disabled=True),
            ])
        ]),
    ])


# ==================== Step 1 disable-toggle callback (fix-16) =========
# Mirrors the disable-toggle pattern used on Steps 3-8 so Next visually
# reflects whether the form is complete. Validation logic is identical
# to submit_step1's `missing_required` — kept duplicated rather than
# extracted into a helper because the toggle runs frequently (every
# Input change) while submit runs once on click; locality of decision
# beats DRY here. submit_step1 still re-validates on click as a fail-
# safe against synthetic clicks.
@dash_app.callback(
    Output("btn-next-step1", "disabled"),
    Input("ownership-type", "value"),
    Input("area", "value"),
    Input("people", "value"),
    Input("occupation", "value"),
    Input("url", "search"),
)
def toggle_step1_next(ownership_type, area, people, occupation, search):
    """Enable Next only when every required field is filled.

    Required: ownership_type, area, people. occupation is conditionally
    required (only when sessions.vec_familiarity is in the top 2 of the
    5-pt scale, i.e. the same gate that decides whether Q5 is even
    visible). der_options is *not* required — a household may legitimately
    have none of PV/BESS/EV.
    """
    from vec_platform.models import Session as SessionModel

    session_id = _parse_session_id(search)
    occupation_required = False
    if session_id:
        _db = SessionLocal()
        try:
            _sess = _db.query(SessionModel).filter(SessionModel.id == session_id).first()
            occupation_required = (
                _sess is not None
                and _sess.vec_familiarity in _EXPERT_FAMILIARITY_GATE
            )
        finally:
            _db.close()

    missing_required = (
        not ownership_type
        or area is None
        or people is None
        or (occupation_required and not occupation)
    )
    # True → button stays disabled; False → enabled.
    return missing_required


# ==================== Step 1 submit callback ====================
# Default sizing for derived DER properties — keeps the v2 MockEngine
# behaviour (5 kWp PV ≈ 3 kW noon peak, 10 kWh battery).
_DEFAULT_PV_KWP = 5.0
_DEFAULT_BESS_KWH = 10.0
_SCENARIOS = ("no_vec", "vec_no_adjust", "vec_adjusted")


@dash_app.callback(
    Output("url", "pathname"),
    Output("url", "search"),
    Output("step1-error", "children"),
    Input("btn-next-step1", "n_clicks"),
    State("ownership-type", "value"),
    State("der-options", "value"),
    State("area", "value"),
    State("people", "value"),
    State("occupation", "value"),
    State("url", "search"),
    prevent_initial_call=True,
)
def submit_step1(n_clicks, ownership_type, der_options, area, people,
                 occupation, search):
    if not n_clicks:
        return no_update, no_update, no_update

    from vec_platform.models import Session as SessionModel, UserInput

    # Phase 3.X-fix-10: occupation is only required when the Q5 widget is
    # actually rendered. The widget is conditionally rendered on a
    # vec_familiarity threshold; for users below the gate the State ref
    # comes back as None (suppress_callback_exceptions=True), and that's
    # a legitimate "not asked" — not a missing answer.
    session_id = _parse_session_id(search)
    occupation_required = False
    if session_id:
        _db = SessionLocal()
        try:
            _sess = _db.query(SessionModel).filter(SessionModel.id == session_id).first()
            occupation_required = (
                _sess is not None
                and _sess.vec_familiarity in _EXPERT_FAMILIARITY_GATE
            )
        finally:
            _db.close()

    missing_required = (
        not ownership_type
        or area is None
        or people is None
        or (occupation_required and not occupation)
    )
    if missing_required:
        return no_update, no_update, "Please answer all questions before continuing."

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
        session.current_step = 2

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
        user_input.ownership_type = ownership_type
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
        # rows and write fresh ones from the updated user_input. This
        # also keeps the existing engine.generate_profile signature
        # intact (engine still expects a freshly-constructed instance,
        # though Phase D-1's recalculate path now reads pv_kwp from
        # user_input on every call anyway).
        db.query(BillBreakdown).filter(
            BillBreakdown.session_id == session_id,
            BillBreakdown.step == 2,
        ).delete(synchronize_session=False)
        db.query(DailyProfile).filter(
            DailyProfile.session_id == session_id,
            DailyProfile.step == 2,
        ).delete(synchronize_session=False)
        db.flush()

        profile = calculation_engine.generate_profile(user_input)
        db.add(profile)
        db.flush()

        for scenario in _SCENARIOS:
            db.add(calculation_engine.calculate_bill(profile, scenario))

        db.commit()
    finally:
        db.close()

    # v3.2b: route through the tenant disclaimer (renters only) or
    # straight to the info-calibration page (owners). Both pages
    # eventually hand off to /step3 (the static customize page, which
    # is "Step 2" in the Phase 4-A 7-step flow — URL preserved per
    # decision 1B).
    if ownership_type == "tenant":
        next_path = "/dash/tenant_disclaimer"
    else:
        next_path = "/dash/info_calibration"
    return next_path, f"?session_id={session_id}", ""
