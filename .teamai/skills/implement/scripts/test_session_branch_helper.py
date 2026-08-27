"""Tests for session branch detection helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "shared" / "scripts" / "detect_session_branch.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("detect_session_branch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_detect_session_branch_matches_default_plan_stem():
    helper = _load_module()

    result = helper.detect_session_branch(
        plan_name="test-env-portability",
        current_branch="feat/test-env-portability-0406",
    )

    assert result["branchStem"] == "test-env-portability"
    assert result["matchesSessionBranch"] is True


def test_detect_session_branch_matches_explicit_branch_stem_and_suffix():
    helper = _load_module()

    result = helper.detect_session_branch(
        plan_name="execution-automation-closure",
        branch_stem="execution-automation-closure-follow-up",
        current_branch="fix/execution-automation-closure-follow-up-0406-2",
    )

    assert result["branchStem"] == "execution-automation-closure-follow-up"
    assert result["matchesSessionBranch"] is True


def test_detect_session_branch_rejects_unrelated_branch():
    helper = _load_module()

    result = helper.detect_session_branch(
        plan_name="execution-automation-closure",
        current_branch="feat/test-env-portability-0406",
    )

    assert result["matchesSessionBranch"] is False
    assert "does not match" in result["reason"]
