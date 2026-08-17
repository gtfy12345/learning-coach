import pytest

from learning_coach.nodes import route_after_assessment
from learning_coach.state import (
    DEFAULT_LEARNING_MODE,
    learning_mode_for_new_session,
    learning_mode_for_state,
)


def test_low_score_routes_to_retry() -> None:
    assert route_after_assessment({"score": 55, "attempts": 1}) == "retry"


def test_passing_score_routes_to_finish() -> None:
    assert route_after_assessment({"score": 80, "attempts": 1}) == "finish"


def test_retry_limit_routes_to_finish() -> None:
    assert route_after_assessment({"score": 55, "attempts": 2}) == "finish"


def test_new_sessions_default_to_teach_first_and_accept_diagnose_first() -> None:
    assert DEFAULT_LEARNING_MODE == "teach_first"
    assert learning_mode_for_new_session(None) == "teach_first"
    assert learning_mode_for_new_session("") == "teach_first"
    assert learning_mode_for_new_session(" diagnose_first ") == "diagnose_first"


def test_new_sessions_reject_unknown_learning_mode() -> None:
    with pytest.raises(ValueError, match="learning_mode"):
        learning_mode_for_new_session("chat")


def test_legacy_state_without_learning_mode_keeps_diagnose_first_semantics() -> None:
    assert learning_mode_for_state({}) == "diagnose_first"
    assert learning_mode_for_state({"learning_mode": "teach_first"}) == "teach_first"
