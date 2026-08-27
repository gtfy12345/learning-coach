"""Tests for the /plan-code-review skill contract."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


class TestPlanCodeReviewSkill:
    """Plan code review should own L2 review and /tdd remediation routing."""

    def test_requires_explicit_plan_name(self):
        text = _skill_text()
        assert "Plan name is mandatory" in text

    def test_uses_shared_validator(self):
        text = _skill_text()
        assert ".agent-skills/implement/shared/scripts/validate_context.py" in text

    def test_reuses_existing_precheck_script(self):
        text = _skill_text()
        assert ".agent-skills/implement/scripts/review_code_precheck.py" in text

    def test_fix_is_routed_through_tdd_section(self):
        text = _skill_text()
        assert "/tdd --file {checklist-path} --section {phase-prefix}" in text
        assert "does not own plan lifecycle sync or retrospective" in text

    def test_target_level_findings_stay_preview_only_without_section_mapping(self):
        text = _skill_text()
        assert "target-level-only findings stay preview-only" in text
        assert "no concrete checklist-section mapping" in text
        assert "preview-only" in text
