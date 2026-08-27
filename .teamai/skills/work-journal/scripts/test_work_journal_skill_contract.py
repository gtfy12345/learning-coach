"""Contract checks for the /work-journal skill instructions."""

from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_declares_auto_mode_arguments():
    text = _skill_text()

    assert "## Usage" in text
    assert "/work-journal --auto --plan <name> --phase <heading>" in text
    assert "## Argument Contract" in text
    assert "`--auto`" in text
    assert "`--plan <name>`" in text
    assert "`--phase <heading>`" in text
    assert "`--auto` must be used together with `--plan` and `--phase`" in text


def test_auto_mode_skips_step_zero():
    text = _skill_text()

    assert "When `--auto` is present, skip Step 0 entirely and continue at Step 1." in text


def test_auto_mode_defines_journal_content_rules():
    text = _skill_text()

    assert "`## HH:MM 工作记录` title remains unchanged" in text
    assert "`### 完成事项`: derive from the phase heading and the checked items completed in that phase" in text
    assert "`### 关联 Commit`: use the commit message derived for the auto-commit" in text
    assert "`### 备注`: `Auto-committed by /tdd phase-commit, plan: {name}`" in text


def test_auto_mode_defines_commit_message_derivation():
    text = _skill_text()

    assert "Auto mode commit message derivation rules:" in text
    assert "`type`: infer from the phase content; default to `feat`" in text
    assert "`scope`: derive from the plan name core term" in text
    assert "`subject`: remove the `Phase N:` prefix from the phase heading and lowercase the remainder" in text
    assert "The full commit message must also include a body summarizing checklist, phase, and completed items." in text


def test_auto_mode_requires_drift_check_stop_behavior():
    text = _skill_text()

    assert "In auto mode, Step 4.5 must attempt automatic drift repair before asking for help." in text
    assert "If drift cannot be repaired automatically, stop the auto-commit and report the remaining drift." in text
