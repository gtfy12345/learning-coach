"""Tests for the /plan-review skill contract."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


class TestPlanReviewSkill:
    """Plan review should own L1 review and document fix behavior."""

    def test_uses_implement_shared_candidate_and_validator(self):
        text = _skill_text()
        assert ".agent-skills/implement/shared/scripts/list_context_candidates.py" in text
        assert ".agent-skills/implement/shared/scripts/validate_context.py" in text

    def test_reuses_existing_review_plan_script(self):
        text = _skill_text()
        assert ".agent-skills/implement/scripts/review_plan.py" in text

    def test_fix_requires_explicit_plan_name(self):
        text = _skill_text()
        assert "requires an explicit plan name" in text

    def test_report_contract_is_present(self):
        text = _skill_text()
        assert "`Findings`" in text
        assert "`Dimension Coverage`" in text
        assert "`Strengths`" in text
        assert "`Optimization Opportunities`" in text
