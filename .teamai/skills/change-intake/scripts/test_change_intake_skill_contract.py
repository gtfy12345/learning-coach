"""Contract checks for the /change-intake skill instructions."""

from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def test_skill_mentions_completed_plan_followup():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "`completed`: **never** reopen the original checklist" in text
    assert "Always create a follow-up or bugfix plan before coding." in text


def test_skill_mentions_matcher_script_and_post_pass_reconcile():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert ".agent-skills/change-intake/scripts/match_change_context.py" in text
    assert "invoke `/retrospective --this` before final close-out" in text
