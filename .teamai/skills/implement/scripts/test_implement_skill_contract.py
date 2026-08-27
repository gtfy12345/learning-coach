"""Tests for the thin /implement skill contract."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


class TestImplementSkillContract:
    """The implement skill should stay thin and execution-focused."""

    def test_review_flags_removed(self):
        text = _skill_text()
        usage_block = text.split("## Shared Resources", 1)[0]
        assert "/implement --review" not in usage_block
        assert "/implement <plan-name> [target] --fix" not in usage_block
        assert "--review-code" not in usage_block
        assert "--fix-code" not in usage_block

    def test_legacy_flags_redirect_to_new_skills(self):
        text = _skill_text()
        assert "The following `/implement` flags no longer exist" in text
        assert "L1 document review/fix → `/plan-review`" in text
        assert "L2 code review/fix → `/plan-code-review`" in text

    def test_shared_resources_are_declared(self):
        text = _skill_text()
        assert ".agent-skills/implement/shared/scripts/list_context_candidates.py" in text
        assert ".agent-skills/implement/shared/scripts/validate_context.py" in text
        assert ".agent-skills/implement/shared/references/plan-context-contract.md" in text

    def test_validator_path_uses_shared_location(self):
        text = _skill_text()
        assert "python3 .agent-skills/implement/shared/scripts/validate_context.py" in text

    def test_sequential_handoff_still_uses_tdd(self):
        text = _skill_text()
        assert "/tdd --file {checklist-path}" in text
        assert "--test-checklist" in text

    def test_description_mentions_continue_and_resume_triggers(self):
        text = _skill_text()
        assert "continue implementing" in text
        assert "resume an in-flight plan" in text

    def test_legacy_parallel_docs_no_longer_drive_dispatch(self):
        text = _skill_text()
        assert "`/implement` no longer performs DAG parsing, Wave dispatch, or teammate fan-out." in text
        assert "All plans, including legacy `parallel` plans, execute through the same sequential `/tdd`" in text
        assert "`/implement` owns the retrospective trigger before final close-out" in text

    def test_branch_resolution_step_exists_before_tdd_handoff(self):
        text = _skill_text()
        assert "### Step 4.5: Branch Resolution" in text
        assert "Insert branch creation and checkout between Step 4 and Step 5." in text
        assert "detect_session_branch.py" in text

    def test_branch_resolution_defines_naming_convention(self):
        text = _skill_text()
        assert "`{type}/{plan-name}-{MMDD}`" in text
        assert "Collision handling: append `-{N}` after the date suffix." in text
        assert "type inference: `fix/`, `opt/`, `docs/`, otherwise `feat/`." in text

    def test_tdd_handoff_passes_phase_commit_plan_name(self):
        text = _skill_text()
        assert "/tdd --file {checklist-path} --references {ref1},{ref2},... --phase-commit {plan-name}" in text

    def test_branch_resolution_checks_for_dirty_working_tree(self):
        text = _skill_text()
        assert "Start Step 4.5 by checking `git status`." in text
        assert "If the working tree has uncommitted changes and the current branch does not match the session feature branch, stop before creating or switching branches." in text

    def test_branch_resolution_allows_dirty_resume_on_session_branch(self):
        text = _skill_text()
        assert "If the current branch already matches the session feature branch, treat the run as retry/resume in place." in text
        assert "A dirty working tree on that branch is a valid resume state; continue into `/tdd` instead of blocking branch creation." in text

    def test_branch_resolution_declares_base_branch_priority_and_retry_resume(self):
        text = _skill_text()
        assert "`context.yaml` `metadata.baseBranch`" in text
        assert "`AGENTS.md` project-level Git branch strategy" in text
        assert "Git default branch auto-detection" in text
        assert "If the current branch is already the session feature branch, treat the run as retry/resume and continue without creating a new branch." in text
