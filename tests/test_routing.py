from learning_coach.nodes import route_after_assessment


def test_low_score_routes_to_retry() -> None:
    assert route_after_assessment({"score": 55, "attempts": 1}) == "retry"


def test_passing_score_routes_to_finish() -> None:
    assert route_after_assessment({"score": 80, "attempts": 1}) == "finish"


def test_retry_limit_routes_to_finish() -> None:
    assert route_after_assessment({"score": 55, "attempts": 2}) == "finish"
