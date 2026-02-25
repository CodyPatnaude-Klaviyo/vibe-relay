"""Tests for db/state_machine.py."""

import pytest

from db.state_machine import (
    InvalidTransitionError,
    get_valid_transitions,
    validate_transition,
)


class TestValidTransitions:
    @pytest.mark.parametrize(
        "current,new",
        [
            ("backlog", "in_progress"),
            ("backlog", "cancelled"),
            ("in_progress", "in_review"),
            ("in_progress", "cancelled"),
            ("in_review", "in_progress"),
            ("in_review", "done"),
            ("in_review", "cancelled"),
        ],
    )
    def test_valid_transition_succeeds(self, current: str, new: str) -> None:
        validate_transition(current, new)  # should not raise

    @pytest.mark.parametrize(
        "current,new",
        [
            ("backlog", "in_review"),
            ("backlog", "done"),
            ("in_progress", "backlog"),
            ("in_progress", "done"),
            ("in_review", "backlog"),
            ("done", "in_progress"),
            ("done", "backlog"),
            ("cancelled", "in_progress"),
            ("cancelled", "backlog"),
        ],
    )
    def test_invalid_transition_raises(self, current: str, new: str) -> None:
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition(current, new)
        assert current in str(exc_info.value)
        assert new in str(exc_info.value)

    def test_unknown_current_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown current status"):
            validate_transition("bogus", "done")

    def test_unknown_target_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown target status"):
            validate_transition("backlog", "bogus")


class TestGetValidTransitions:
    def test_backlog(self) -> None:
        assert get_valid_transitions("backlog") == ["cancelled", "in_progress"]

    def test_in_progress(self) -> None:
        assert get_valid_transitions("in_progress") == ["cancelled", "in_review"]

    def test_in_review(self) -> None:
        assert get_valid_transitions("in_review") == ["cancelled", "done", "in_progress"]

    def test_terminal_states_have_no_transitions(self) -> None:
        assert get_valid_transitions("done") == []
        assert get_valid_transitions("cancelled") == []

    def test_unknown_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown status"):
            get_valid_transitions("bogus")
