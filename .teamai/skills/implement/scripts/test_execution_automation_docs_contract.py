"""Doc contract checks for execution automation closure."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
PLAN_CONTEXT_CONTRACT_PATH = (
    REPO_ROOT / ".agent-skills" / "implement" / "shared" / "references" / "plan-context-contract.md"
)


def _agents_text() -> str:
    return AGENTS_PATH.read_text(encoding="utf-8")


def _plan_context_contract_text() -> str:
    return PLAN_CONTEXT_CONTRACT_PATH.read_text(encoding="utf-8")


def test_agents_declares_git_branch_strategy_section():
    text = _agents_text()

    assert "## 7 Git 分支策略" in text
    assert "- 默认父分支:" in text
    assert "- `/implement` 自动从父分支创建 feature branch" in text
    assert "- phase commit 后自动 merge 回父分支" in text


def test_agents_work_journal_row_mentions_dual_mode():
    text = _agents_text()

    assert "| `/work-journal` | 记录工作日志并提交 | 显式调用 + `/tdd` phase-commit | 用户决定提交时机 / phase 边界自动提交时 |" in text


def test_agents_declares_continue_resume_must_reenter_implement():
    text = _agents_text()

    assert "继续已有计划或恢复当前 plan 执行 → 必须调用 `/implement`" in text


def test_plan_context_contract_mentions_branch_metadata_usage():
    text = _plan_context_contract_text()

    assert "| `metadata.baseBranch` | string | No | Base branch and merge target used by `/implement` Step 4.5 |" in text
    assert "| `metadata.branch` | string | No | Feature branch name stem used by `/implement` Step 4.5 before the date/collision suffix is appended |" in text
    assert "1. `context.yaml` `metadata.baseBranch`" in text
    assert "2. `AGENTS.md` project-level Git branch strategy" in text
    assert "3. Git default branch auto-detection" in text
