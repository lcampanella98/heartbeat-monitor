"""Unit tests for streak/incident transition logic.

These tests exercise the state-machine rules via a pure in-process simulation —
no DB or session required. This lets us run table-driven tests across many
sequences quickly and cheaply.

NOTE: `apply_check_result` itself is NOT called here. The simulation mirrors
its logic by hand, so divergence between the two is only caught by the
integration suite (`tests/integration/test_incidents.py`). Both test layers
are necessary.
"""

import pytest

from heartbeat.models.endpoint import StreakOutcome
from heartbeat.services.incident_service import M, N

S = StreakOutcome.success
F = StreakOutcome.failure


def simulate_sequence(
    outcomes: list[StreakOutcome],
) -> tuple[int, int, bool]:
    """Simulate the streak/incident state machine over a sequence of outcomes.

    Returns:
        (incidents_opened, incidents_closed, has_open_incident_at_end)
    """
    streak_outcome: StreakOutcome | None = None
    streak_count = 0
    has_open_incident = False
    incidents_opened = 0
    incidents_closed = 0

    for outcome in outcomes:
        if outcome == streak_outcome:
            streak_count += 1
        else:
            streak_outcome = outcome
            streak_count = 1

        if streak_outcome == F and streak_count == N:
            if not has_open_incident:
                has_open_incident = True
                incidents_opened += 1
        elif streak_outcome == S and streak_count == M:
            if has_open_incident:
                has_open_incident = False
                incidents_closed += 1

    return incidents_opened, incidents_closed, has_open_incident


@pytest.mark.parametrize(
    "outcomes, exp_opened, exp_closed, exp_open",
    [
        # Basic: 3 failures open, 2 successes close
        ([S, S, F, F, F, S, S], 1, 1, False),
        # Failures from the start (no preceding success)
        ([F, F, F, F, S, S], 1, 1, False),
        # Success resets partial failure streak, then a full failure streak opens
        ([F, F, S, F, F, F, S, S], 1, 1, False),
        # Incident already open: N more failures do not open a second incident
        ([F, F, F, F, F, S, S], 1, 1, False),
        # Not enough failures to open
        ([F, F, S], 0, 0, False),
        # Single success inside an open incident does not close it (need M=2)
        ([F, F, F, S, F, F, F], 1, 0, True),
        # Open, close, then open again
        ([F, F, F, S, S, F, F, F], 2, 1, True),
        # Success streak resets in middle of failures: partial F,F,S resets, then F,F,F opens
        ([F, F, S, F, F], 0, 0, False),
        # Exact N failures, exact M successes — boundary
        ([F, F, F, S, S], 1, 1, False),
        # No incidents at all
        ([S, S, S], 0, 0, False),
        # Stays open after partial success then more failures
        ([F, F, F, S, F, F], 1, 0, True),
    ],
)
def test_simulate_sequence(
    outcomes: list[StreakOutcome],
    exp_opened: int,
    exp_closed: int,
    exp_open: bool,
) -> None:
    opened, closed, has_open = simulate_sequence(outcomes)
    assert opened == exp_opened
    assert closed == exp_closed
    assert has_open == exp_open
