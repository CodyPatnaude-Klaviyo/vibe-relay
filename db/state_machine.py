"""Task status state machine for vibe-relay.

Valid transitions:
    backlog     -> in_progress, cancelled
    in_progress -> in_review, cancelled
    in_review   -> in_progress, done, cancelled
    done        -> (terminal)
    cancelled   -> (terminal)

Import validate_transition() from here. Do not duplicate this logic.
"""

VALID_STATUSES = {"backlog", "in_progress", "in_review", "done", "cancelled"}
VALID_PHASES = {"planner", "coder", "reviewer", "orchestrator"}
VALID_AUTHOR_ROLES = {"planner", "coder", "reviewer", "orchestrator", "human"}

TRANSITIONS: dict[str, set[str]] = {
    "backlog": {"in_progress", "cancelled"},
    "in_progress": {"in_review", "cancelled"},
    "in_review": {"in_progress", "done", "cancelled"},
    "done": set(),
    "cancelled": set(),
}


class InvalidTransitionError(Exception):
    """Raised when a status transition is not allowed by the state machine."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        valid = sorted(TRANSITIONS.get(current, set()))
        super().__init__(
            f"Cannot move task from '{current}' to '{requested}'. "
            f"Valid next states: {valid}"
        )


def validate_transition(current_status: str, new_status: str) -> None:
    """Validate a task status transition. Raises InvalidTransitionError if invalid."""
    if current_status not in VALID_STATUSES:
        raise ValueError(f"Unknown current status: '{current_status}'")
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Unknown target status: '{new_status}'")
    if new_status not in TRANSITIONS[current_status]:
        raise InvalidTransitionError(current_status, new_status)


def get_valid_transitions(current_status: str) -> list[str]:
    """Return the list of valid next statuses for the given current status."""
    if current_status not in VALID_STATUSES:
        raise ValueError(f"Unknown status: '{current_status}'")
    return sorted(TRANSITIONS[current_status])
