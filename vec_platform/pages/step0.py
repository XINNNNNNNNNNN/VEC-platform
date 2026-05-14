"""Step 0 — Welcome page (Phase O-fix-11 redesign).

The Welcome route splits into two visually-distinct states inside one
URL (no new route, no extra page module):

  State 1 — Consent
    * Neutral VEC description in Ei (Energimarknadsinspektionen)
      regulatory language — does NOT mention "savings", "discount", or
      "better price" so the description can't anchor the participant's
      Layer 1 threshold response in State 2.
    * Expandable GDPR + Swedish Ethical Review Act 2003:460 consent
      form. Default-collapsed; participant must click [+] to reveal
      the checkbox. Forces a deliberate read.
    * Phase O-fix-10 disabled-look Next button: gray until the consent
      checkbox is ticked, click-through preserved so the participant
      gets an inline hint instead of a dead button.

  State 2 — Familiarity + threshold
    * 5-radio familiarity (preserves the exact string values that
      _EXPERT_FAMILIARITY_GATE in step7 depends on — changing these
      would silently break the expert gate).
    * Threshold slider 0–50 % (entry_threshold_pct). Initial value 0
      but tracked separately via a touched-flag store: the user MUST
      drag the slider before Next becomes blue, so we don't conflate
      "didn't answer" with "would join for any saving".
    * Same disabled-look Next + per-Q inline hints.

Persistence:
  * sessions.vec_familiarity   ← familiarity radio
  * user_inputs.entry_threshold_pct  ← threshold slider (Phase O-fix-11
    alembic migration 7c4d9f1e2a8b added this column).
  * NOT prior_expectations.* — that table keeps the existing
    "expected savings" semantic and is written by Step 1 / Step 3
    in a future fix.

Importing this module registers six Dash callbacks against
``dash_app``. Function names start with ``welcome_`` so they don't
collide with the legacy ``step0_*`` callback names that earlier
revisions defined.
"""

from dash import html, dcc, no_update
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc

from vec_platform.runtime import dash_app, SessionLocal
from vec_platform.pages._helpers import _parse_session_id


# ==================== Welcome (Step 0) ====================

# Ei-neutral VEC description. Deliberately avoids "reduce bills",
# "discount", "better price", "savings come from how the community
# settles" — those phrasings used to live here (pre-fix-11) and
# anchored participants toward expecting savings before they'd seen
# any data. The replacement copy mirrors Energimarknadsinspektionen's
# regulatory definition and is explicit that whether participation
# pays off is conditional on amount / timing / sharing prices / fees
# and taxes — the participant decides whether to expect savings.
_VEC_DESCRIPTION_LINE_1 = (
    "A group of households in the same electricity area (elområde) "
    "that share locally produced renewable electricity through the "
    "public grid. Households with solar panels can share their surplus "
    "with neighbours; participants who use that shared energy have it "
    "deducted from their total billed consumption."
)
_VEC_DESCRIPTION_LINE_2 = (
    "You keep your existing electricity contract and meter. Whether "
    "participation results in savings depends on how much energy is "
    "shared, when it is shared, the agreed sharing prices, and grid "
    "fees and taxes that still apply."
)


# v3.X-fix-7 — these exact string values feed _EXPERT_FAMILIARITY_GATE
# in pages/step7.py. Renaming them silently breaks the Q5 gate logic
# in step1.py and the expert-only block in step7.py.
_VEC_FAMILIARITY_OPTIONS = [
    {"label": "Never heard of it",                              "value": "never_heard"},
    {"label": "Heard of it, but don't really understand it",    "value": "heard_no_understand"},
    {"label": "Somewhat familiar",                              "value": "somewhat_familiar"},
    {"label": "Very familiar",                                  "value": "very_familiar"},
    {"label": "Have participated in a similar initiative",      "value": "have_participated"},
]

_SLIDER_MARKS = {p: f"{p}%" for p in (0, 10, 20, 30, 40, 50)}

# Phase O-fix-11: shared className constants so the visual rules can't
# drift between the two state-Next callbacks.
_CLS_BTN_ENABLED = "mt-2"
_CLS_BTN_DISABLED = "mt-2 disabled-look"


def _consent_form_body():
    """Phase O-fix-11: full GDPR + Swedish Ethical Review Act consent.

    Rendered inside the collapsed `consent-content` Div so the
    participant must explicitly expand it to see the checkbox at the
    bottom. Heading copy is anchored to KTH × E.ON × Energimyndigheten
    so the participant can identify the institutions handling their
    data.
    """
    return dbc.Card(dbc.CardBody([
        html.H4("INFORMED CONSENT — VEC Research Study (KTH × E.ON)",
                className="mb-3"),

        html.H5("Purpose"),
        html.P(
            "We are studying how households think about Virtual Energy "
            "Communities (energidelning). Data will be used in "
            "scientific research on energy policy and behavior, "
            "conducted at KTH Royal Institute of Technology in "
            "collaboration with E.ON Energidistribution AB, funded by "
            "Energimyndigheten (Swedish Energy Agency)."
        ),

        html.H5("What we collect"),
        html.Ul([
            html.Li("Your responses to the questions in this 25-minute "
                    "survey"),
            html.Li("Your home characteristics you choose to share "
                    "(size, occupants, type)"),
            html.Li("Your timing decisions in the device-scheduling "
                    "task"),
            html.Li("Anonymous session identifier (no name, no email, "
                    "no IP address stored)"),
        ]),

        html.H5("How we protect your data"),
        html.Ul([
            html.Li("All data is anonymous. No personal identifiers "
                    "are recorded."),
            html.Li("Data is stored on KTH and EU-based servers, in "
                    "accordance with GDPR."),
            html.Li("Legal basis: research in the public interest "
                    "(GDPR Art. 6(1)(e), Higher Education Act "
                    "1992:1434)."),
            html.Li("Data will be analysed in aggregate. Anonymous "
                    "datasets may be published with academic results."),
        ]),

        html.H5("Your rights"),
        html.Ul([
            html.Li("Participation is voluntary. You may close this "
                    "browser tab at any time to withdraw, without "
                    "giving a reason."),
            html.Li("Since data is anonymous, individual responses "
                    "cannot be retrieved or deleted after submission "
                    "(the anonymous session ID is not linked to you)."),
            html.Li("This study does not involve health data, criminal "
                    "data, or physical intervention. It is not subject "
                    "to mandatory ethical review under the Swedish "
                    "Ethical Review Act (2003:460)."),
        ]),

        html.P([html.Strong("Time commitment: "), "~25 minutes"]),
        html.P([html.Strong("Compensation: "), "none"]),

        html.H5("Research team"),
        html.Ul([
            html.Li(["Dr Xin Lu (KTH) — ",
                     html.A("xinl5@kth.se", href="mailto:xinl5@kth.se")]),
            html.Li(["Prof. Qianwen Xu (KTH) — ",
                     html.A("qianwenx@kth.se",
                            href="mailto:qianwenx@kth.se")]),
            html.Li(["Linnea Ljungberg (E.ON Energidistribution AB) — ",
                     html.A("linnea.ljungberg@eon.se",
                            href="mailto:linnea.ljungberg@eon.se")]),
        ]),

        html.Hr(),

        # The checkbox is INSIDE the consent body — it's not reachable
        # until the participant has expanded the form. That's the
        # whole point of the collapse-by-default pattern.
        dbc.Checkbox(
            id="welcome-consent-checkbox",
            label=("I confirm I am 18 years or older, have read the "
                   "information above, and voluntarily agree to "
                   "participate."),
            value=False,
            className="mt-3",
        ),
    ]), className="consent-card")


def step0_layout(session_id: str | None = None):
    """Phase O-fix-11: two-state Welcome layout in a single render.

    Both states are rendered into the DOM up front. State 2 starts at
    ``display:none`` and the state1-submit callback toggles the
    visibility on a valid consent. We deliberately don't render the
    states conditionally on the server — keeping both components in
    the layout makes the callback graph valid for every
    Output/Input pairing without needing
    ``suppress_callback_exceptions=True`` gymnastics.
    """
    session_note = (
        dbc.Alert(f"Session: {session_id}", color="light",
                  className="py-2 small")
        if session_id else
        dbc.Alert(
            "No active session — open the site from '/' to create one.",
            color="warning", className="py-2 small",
        )
    )

    # ---- State 1: consent ----
    state_1 = html.Div([
        html.H2("Welcome"),
        html.P(
            "We're studying how households would interact with a "
            "Virtual Energy Community. Before we show you any numbers, "
            "we'd like to introduce the concept and ask for your "
            "consent to participate."
        ),

        session_note,

        # Neutral VEC description — see _VEC_DESCRIPTION_* notes above
        # for why the leading-language version was replaced.
        html.Div([
            html.Div([
                html.Strong("Virtual Energy Community (VEC): "),
                html.Span(_VEC_DESCRIPTION_LINE_1),
            ]),
            html.Br(),
            html.P(_VEC_DESCRIPTION_LINE_2, className="mb-0"),
        ], className="vec-description-box mb-3"),

        html.H3("Consent", className="mb-2 mt-4"),

        # Expand toggle. n_clicks parity decides expanded/collapsed.
        html.Button(
            [
                html.Span("[+] ", id="consent-expand-icon"),
                html.Span("Click to read the consent form and contact "
                          "information",
                          id="consent-expand-text"),
            ],
            id="consent-expand-btn",
            n_clicks=0,
            className="consent-expand-btn mb-2",
            type="button",
        ),

        html.Div(
            _consent_form_body(),
            id="consent-content",
            style={"display": "none"},
        ),

        # Inline hint Div (Phase O-fix-10 pattern).
        html.Div(id="welcome-state1-hint", className="step1-hint-text mt-2"),

        # Next — disabled-look until consent checkbox is ticked. NEVER
        # uses the HTML disabled prop (Phase O-fix-10 rationale).
        dbc.Button(
            "Next",
            id="welcome-state1-next",
            color="primary",
            size="lg",
            className=_CLS_BTN_DISABLED,
            n_clicks=0,
        ),
    ], id="welcome-state-1")

    # ---- State 2: familiarity + threshold ----
    state_2 = html.Div([
        html.H2("A few quick questions", className="mb-3"),
        html.P(
            "These help us understand your starting point.",
            className="text-muted mb-4",
        ),

        # Familiarity question.
        html.Div([
            html.Label(
                "How familiar are you with this concept?",
                className="form-label fw-bold mb-2",
            ),
            dcc.RadioItems(
                id="welcome-familiarity-radio",
                options=_VEC_FAMILIARITY_OPTIONS,
                value=None,
                labelStyle={"display": "block", "padding": "0.2rem 0"},
            ),
            html.Div(id="welcome-familiarity-hint",
                     className="step1-hint-text"),
        ], className="mb-4"),

        # Threshold slider.
        html.Div([
            html.Label(
                "In general, how much saving would you need before "
                "considering joining such a community?",
                className="form-label fw-bold mb-2",
            ),
            html.Small(
                "0% = no saving needed (environmental / social "
                "reasons). 50% = would only join with very high "
                "savings.",
                className="text-muted mb-3 d-block",
            ),
            dcc.Slider(
                id="welcome-threshold-slider",
                min=0, max=50, step=1, value=0,
                marks=_SLIDER_MARKS,
                tooltip={"placement": "bottom", "always_visible": False},
            ),
            html.Div(
                "Threshold: — % (move the slider to set)",
                id="welcome-threshold-display",
                className="mt-2 text-muted",
            ),
            html.Div(id="welcome-threshold-hint",
                     className="step1-hint-text"),
        ], className="mb-4"),

        dbc.Button(
            "Next",
            id="welcome-state2-next",
            color="primary",
            size="lg",
            className=_CLS_BTN_DISABLED,
            n_clicks=0,
        ),

        # Phase O-fix-11: tracks whether the participant has interacted
        # with the slider. Default value 0 by itself can't tell
        # "moved slider to 0" from "never touched it"; the store
        # flips True on the first slider change event and stays True
        # for the rest of the page lifecycle.
        dcc.Store(id="welcome-threshold-touched-store", data=False),

    ], id="welcome-state-2", style={"display": "none"})

    return html.Div([state_1, state_2])


# ===================== Callbacks =====================

@dash_app.callback(
    Output("consent-content", "style"),
    Output("consent-expand-icon", "children"),
    Output("consent-expand-text", "children"),
    Input("consent-expand-btn", "n_clicks"),
    prevent_initial_call=True,
)
def welcome_toggle_consent(n_clicks):
    """Expand / collapse the consent form. Odd clicks = expanded."""
    if (n_clicks or 0) % 2 == 1:
        return ({"display": "block"}, "[-] ", "Hide consent form")
    return (
        {"display": "none"},
        "[+] ",
        "Click to read the consent form and contact information",
    )


@dash_app.callback(
    Output("welcome-state1-next", "className"),
    Input("welcome-consent-checkbox", "value"),
)
def welcome_state1_next_visual(consent):
    """Phase O-fix-10 disabled-look toggle for the State 1 Next button."""
    return _CLS_BTN_ENABLED if consent else _CLS_BTN_DISABLED


@dash_app.callback(
    Output("welcome-state1-hint", "children"),
    Output("welcome-state-1", "style"),
    Output("welcome-state-2", "style"),
    Input("welcome-state1-next", "n_clicks"),
    State("welcome-consent-checkbox", "value"),
    prevent_initial_call=True,
)
def welcome_state1_submit(n_clicks, consent):
    """Validate consent. If unchecked, surface an inline hint; if
    checked, hide State 1 and reveal State 2 in the same DOM."""
    if not consent:
        return (
            "⚠ Please review and agree to the consent form to "
            "continue.",
            no_update,
            no_update,
        )
    return ("", {"display": "none"}, {})


@dash_app.callback(
    Output("welcome-threshold-touched-store", "data"),
    Output("welcome-threshold-display", "children"),
    Input("welcome-threshold-slider", "value"),
    prevent_initial_call=True,
)
def welcome_track_threshold(value):
    """First slider interaction flips the touched flag to True. The
    flag never goes back to False — even if the participant drags
    the slider back to 0, they have actively answered with 0."""
    return True, f"Threshold: {int(value)} %"


@dash_app.callback(
    Output("welcome-state2-next", "className"),
    Input("welcome-familiarity-radio", "value"),
    Input("welcome-threshold-touched-store", "data"),
)
def welcome_state2_next_visual(familiarity, touched):
    """Both familiarity radio and slider-touched must be true for
    the Next button to leave disabled-look."""
    if familiarity and touched:
        return _CLS_BTN_ENABLED
    return _CLS_BTN_DISABLED


# Phase O-fix-11 follow-up: per-Q hint-clear callbacks (mirror the
# Phase O-fix-10 step1.py pattern). Without these, hints set by a
# failed welcome_state2_submit click stay on screen even after the
# participant fixes the matching field, which made it look as if
# State 2 entered with pre-existing hints.
#
# allow_duplicate=True is required because welcome_state2_submit also
# writes to these Outputs; Dash >= 2.9 supports the dup as long as
# prevent_initial_call=True is set on the duplicate.
@dash_app.callback(
    Output("welcome-familiarity-hint", "children", allow_duplicate=True),
    Input("welcome-familiarity-radio", "value"),
    prevent_initial_call=True,
)
def _welcome_clear_familiarity_hint(_value):
    return ""


@dash_app.callback(
    Output("welcome-threshold-hint", "children", allow_duplicate=True),
    Input("welcome-threshold-slider", "value"),
    prevent_initial_call=True,
)
def _welcome_clear_threshold_hint(_value):
    return ""


@dash_app.callback(
    Output("welcome-familiarity-hint", "children"),
    Output("welcome-threshold-hint", "children"),
    Output("url", "pathname"),
    Output("url", "search"),
    Input("welcome-state2-next", "n_clicks"),
    State("welcome-familiarity-radio", "value"),
    State("welcome-threshold-slider", "value"),
    State("welcome-threshold-touched-store", "data"),
    State("url", "search"),
    prevent_initial_call=True,
)
def welcome_state2_submit(_n_clicks, familiarity, threshold_pct, touched,
                          search):
    """Validate familiarity + threshold-touched, then write to DB and
    navigate to /step1.

    DB writes are minimal: ``sessions.vec_familiarity`` and a new (or
    upserted) ``user_inputs.entry_threshold_pct``. The
    ``prior_expectations`` table is intentionally NOT touched — that
    table keeps the "expected savings" semantic and will be written
    by a later step's expectation question, not by this threshold
    question (Phase O-fix-11 schema decision).

    ``prevent_initial_call=True`` on the decorator means the callback
    cannot fire with n_clicks=0, so the parameter is only needed to
    keep the positional alignment with the @callback Input list — the
    leading underscore silences the unused-parameter linter.
    """
    fam_hint = ""
    thr_hint = ""
    if not familiarity:
        fam_hint = "⚠ Please select an option."
    if not touched:
        thr_hint = "⚠ Please move the slider to set your threshold."
    if fam_hint or thr_hint:
        return fam_hint, thr_hint, no_update, no_update

    session_id = _parse_session_id(search)
    if not session_id:
        # Defensive — Step 0 should always have a session. Surface as
        # a familiarity-hint message because there's no dedicated
        # "page-level" error placeholder on the Welcome layout.
        return (
            "⚠ Session id missing — please start from '/'.",
            "",
            no_update, no_update,
        )

    from vec_platform.models import Session as SessionModel, UserInput

    db = SessionLocal()
    try:
        sess = (
            db.query(SessionModel)
            .filter(SessionModel.id == session_id)
            .first()
        )
        if sess is None:
            return (
                "⚠ Session not found — please start from '/'.",
                "",
                no_update, no_update,
            )

        sess.vec_familiarity = familiarity
        # Idempotent step-counter nudge (don't go backwards if the
        # participant pressed Back from Step 1).
        if sess.current_step is None or sess.current_step < 1:
            sess.current_step = 1

        # Upsert user_inputs.entry_threshold_pct. Step 1 will later see
        # this row and update its own fields (building_type, area, …)
        # without disturbing entry_threshold_pct.
        ui = (
            db.query(UserInput)
            .filter(UserInput.session_id == session_id)
            .first()
        )
        if ui is None:
            ui = UserInput(session_id=session_id)
            db.add(ui)
        ui.entry_threshold_pct = float(threshold_pct)

        db.commit()
    finally:
        db.close()

    return "", "", "/dash/step1", f"?session_id={session_id}"
