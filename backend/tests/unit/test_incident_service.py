"""Unit tests for streak_step pure function."""

from datetime import UTC, datetime, timedelta

import pytest

from heartbeat.models.endpoint import StreakOutcome
from heartbeat.services.incident_service import N, M, StreakState, streak_step

_FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TICK = timedelta(seconds=60)

S = StreakOutcome.success
F = StreakOutcome.failure


def _run_streak_sequence(outcomes: list[StreakOutcome]) -> tuple[int, int, bool]:
    """Drive streak_step through a sequence, tracking incident open/close events.

    Returns (opened, closed, has_open_at_end).
    """
    state = StreakState(outcome=None, count=0, started_at=None)
    t = _FIXED_NOW
    opened = 0
    closed = 0
    has_open = False

    for outcome in outcomes:
        decision = streak_step(state, outcome, t)
        state = decision.next_state

        if decision.open_at is not None and not has_open:
            opened += 1
            has_open = True

        if decision.close_at is not None and has_open:
            closed += 1
            has_open = False

        t += _TICK

    return opened, closed, has_open


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
        # Success resets partial failure streak; F,F,S,F,F never reaches N
        ([F, F, S, F, F], 0, 0, False),
        # Exact N failures, exact M successes — boundary
        ([F, F, F, S, S], 1, 1, False),
        # No incidents at all
        ([S, S, S], 0, 0, False),
        # Stays open after partial success then more failures
        ([F, F, F, S, F, F], 1, 0, True),
    ],
)
def test_streak_step_sequence(
    outcomes: list[StreakOutcome],
    exp_opened: int,
    exp_closed: int,
    exp_open: bool,
) -> None:
    opened, closed, has_open = _run_streak_sequence(outcomes)
    assert opened == exp_opened
    assert closed == exp_closed
    assert has_open == exp_open


def test_streak_step_open_at_is_first_failure_time() -> None:
    """open_at should equal the timestamp of the first failure, not the Nth."""
    t0 = _FIXED_NOW
    state = StreakState(outcome=None, count=0, started_at=None)

    d1 = streak_step(state, F, t0)
    d2 = streak_step(d1.next_state, F, t0 + _TICK)
    d3 = streak_step(d2.next_state, F, t0 + 2 * _TICK)

    assert d3.open_at == t0  # first failure's time, not the third


def test_streak_step_close_at_is_first_success_time() -> None:
    """close_at should equal the timestamp of the first success in the closing streak."""
    t0 = _FIXED_NOW
    state = StreakState(outcome=None, count=0, started_at=None)

    # Open an incident
    for i, outcome in enumerate([F, F, F]):
        decision = streak_step(state, outcome, t0 + i * _TICK)
        state = decision.next_state

    # First closing success
    t_s1 = t0 + 3 * _TICK
    d_s1 = streak_step(state, S, t_s1)
    state = d_s1.next_state

    # Second closing success (hits M=2, triggers close)
    t_s2 = t0 + 4 * _TICK
    d_s2 = streak_step(state, S, t_s2)

    assert d_s2.close_at == t_s1  # first success's time, not the second
