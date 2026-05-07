"""Helpers shared across two or more page modules.

Anything used by only one ``stepN.py`` lives in that file, not here. The
rule: if you grep a name and it has fewer than two callers across pages,
move it back into the page that uses it.
"""

from urllib.parse import parse_qs

from dash import html


# ----- URL / progress bar -----

def _parse_session_id(search: str | None) -> str | None:
    """Parse ``session_id`` out of a Dash ``url.search`` query string.

    Used by the routing callback in main.py and by the Step 1 + Step 8
    submit callbacks.
    """
    if not search:
        return None
    qs = parse_qs(search.lstrip("?"))
    values = qs.get("session_id")
    return values[0] if values else None


def make_progress(current_step: int = 0):
    """Eight little pill-shaped badges showing where the participant is.

    Phase 4-A renumbered the flow: the old "Profile" page (mock baseline
    display, formerly Step 2) was removed because participants couldn't
    internalise its mock data and it polluted later willingness anchors.
    The badge row is now 8 pills (Step 0 + Steps 1..7) and uses 0-based
    indexing throughout (current_step ∈ {0..7} for active steps; 8 means
    "completed").

    Called from the routing callback for each step.
    """
    steps = [
        "0. Welcome", "1. Role", "2. Customize", "3. Prices",
        "4. Respond", "5. Compare", "6. Impacts", "7. Survey",
    ]
    items = []
    for i, label in enumerate(steps):
        if i < current_step:
            items.append(html.Span(label, className="badge bg-success me-1"))
        elif i == current_step:
            items.append(html.Span(label, className="badge bg-primary me-1"))
        else:
            items.append(html.Span(label, className="badge bg-secondary me-1"))
    return html.Div(items, className="mb-3")


# ----- Time / DB lookups -----

def _slot_to_hour(slot: int) -> float:
    """Convert a 15-minute slot index (0..95) to fractional hour-of-day.

    Used by Step 2's load-curve figure, Step 4's price figure and Step 6's
    comparison figure.
    """
    return slot * 15 / 60.0


def _get_profile_at_step(db, session_id: str, step: int):
    """Latest ``DailyProfile`` for a session at a given step (or None).

    Used by Step 6's bill comparison and Step 7's impact computation.
    """
    from vec_platform.models import DailyProfile
    return (
        db.query(DailyProfile)
        .filter(DailyProfile.session_id == session_id, DailyProfile.step == step)
        .order_by(DailyProfile.id.desc())
        .first()
    )
