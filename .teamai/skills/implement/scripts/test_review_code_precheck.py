"""Tests for review_code_precheck.py (Phase 6: L2 Pre-check)."""
import json
import os
import subprocess
import sys
import tempfile

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "review_code_precheck.py")
PYTHON = sys.executable


def _setup_precheck_env(tmp_path, plan_content, cl_content, code_files=None):
    """Create plan, checklist, files.json, and optional code files for precheck tests.

    Args:
        code_files: dict of {relative_path: content} to create in tmp_path
    Returns:
        (files_json_path, project_root)
    """
    plan_path = str(tmp_path / "plan.md")
    cl_path = str(tmp_path / "checklist.md")
    with open(plan_path, "w") as f:
        f.write(plan_content)
    with open(cl_path, "w") as f:
        f.write(cl_content)

    if code_files:
        for rel_path, content in code_files.items():
            full_path = tmp_path / rel_path
            os.makedirs(str(full_path.parent), exist_ok=True)
            with open(str(full_path), "w") as f:
                f.write(content)

    files_json = {
        "files": [
            {"role": "plan", "path": plan_path},
            {"role": "checklist", "path": cl_path},
        ]
    }
    fj_path = str(tmp_path / "files.json")
    with open(fj_path, "w") as f:
        json.dump(files_json, f)

    return fj_path, str(tmp_path)


# --- 6.1 R-001 Code file existence ---


class TestR001CodeFileExistence:
    """R-001: [x] items must have corresponding code files."""

    def test_checked_item_file_exists(self, tmp_path):
        """6.1.1: [x] item + file exists and non-empty → pass."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/handler.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/handler.py": "def handle(): pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        r001_results = [r for r in data["precheck_results"] if r["check_id"] == "R-001"]
        assert all(r["status"] == "pass" for r in r001_results)

    def test_checked_item_file_missing(self, tmp_path):
        """6.1.2: [x] item + file does not exist → fail."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/missing.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        r001_results = [r for r in data["precheck_results"] if r["check_id"] == "R-001"]
        assert any(r["status"] == "fail" for r in r001_results)

    def test_checked_item_file_empty(self, tmp_path):
        """6.1.3: [x] item + file is empty (0 bytes) → fail."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/empty.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/empty.py": ""}  # empty file
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        r001_results = [r for r in data["precheck_results"] if r["check_id"] == "R-001"]
        assert any(r["status"] == "fail" for r in r001_results)

    def test_unchecked_item_skipped(self, tmp_path):
        """6.1.4: [ ] item → not checked."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/missing.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        r001_results = [r for r in data["precheck_results"] if r["check_id"] == "R-001"]
        # No R-001 failures for unchecked items
        assert not any(r["status"] == "fail" for r in r001_results)

    def test_multi_task_phase_checks_only_current_item_files(self, tmp_path):
        """6.1.5: Same-phase tasks must not cross-check each other's files."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/handler.py`\n\n"
            "#### 1.2 Create service\n\n**文件**: `src/service.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n"
            "- [x] 1.1 Create handler\n"
            "- [x] 1.2 Create service\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/handler.py": "def handle(): pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        r001_results = [r for r in data["precheck_results"] if r["check_id"] == "R-001"]
        assert ("1.1", "src/handler.py", "pass") in [
            (r["item_id"], r["file"], r["status"]) for r in r001_results
        ]
        assert not any(r["item_id"] == "1.1" and r["file"] == "src/service.py"
                       for r in r001_results)
        assert any(r["item_id"] == "1.2" and r["file"] == "src/service.py"
                   and r["status"] == "fail" for r in r001_results)


# --- 6.2 P-004 Plan-declared file existence ---


class TestP004PlanDeclaredFiles:
    """P-004: Plan-declared files within phase scope must exist."""

    def test_all_files_exist(self, tmp_path):
        """6.2.1: All declared files exist → pass."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/handler.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/handler.py": "def handle(): pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        p004_results = [r for r in data["precheck_results"] if r["check_id"] == "P-004"]
        assert all(r["status"] == "pass" for r in p004_results)

    def test_some_files_missing(self, tmp_path):
        """6.2.2: Some declared files missing → fail."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/handler.py`, `src/missing.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/handler.py": "def handle(): pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        p004_results = [r for r in data["precheck_results"] if r["check_id"] == "P-004"]
        assert any(r["status"] == "fail" for r in p004_results)

    def test_glob_matches(self, tmp_path):
        """6.2.3: Glob expands to at least 1 file → pass."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: parallel\n\n"
            "### W1.Auth: Auth\n"
            "<!-- agent: apiserver-auth -->\n"
            "<!-- depends-on: — -->\n"
            "<!-- files: src/*.py -->\n\n"
            "#### W1.Auth.1 Create auth\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## W1.Auth: Auth\n\n- [x] W1.Auth.1 Create auth\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/auth.py": "class Auth: pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "W1.Auth"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        p004_results = [r for r in data["precheck_results"] if r["check_id"] == "P-004"]
        assert all(r["status"] == "pass" for r in p004_results)

    def test_glob_no_match(self, tmp_path):
        """6.2.4: Glob with no matches → fail."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: parallel\n\n"
            "### W1.Auth: Auth\n"
            "<!-- agent: apiserver-auth -->\n"
            "<!-- depends-on: — -->\n"
            "<!-- files: src/nonexistent/*.go -->\n\n"
            "#### W1.Auth.1 Create auth\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## W1.Auth: Auth\n\n- [x] W1.Auth.1 Create auth\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "W1.Auth"],
            capture_output=True, text=True, cwd=root,
        )
        data = json.loads(result.stdout)
        p004_results = [r for r in data["precheck_results"] if r["check_id"] == "P-004"]
        assert any(r["status"] == "fail" for r in p004_results)


# --- 6.3 L2 CLI & exit codes ---


class TestL2CliExitCodes:
    """L2 precheck CLI and exit code semantics."""

    def test_all_pass_exit_0(self, tmp_path):
        """6.3.1: All checks pass → exit 0, summary.fail=0."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/handler.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(
            tmp_path, plan, cl,
            code_files={"src/handler.py": "def handle(): pass\n"}
        )

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["summary"]["fail"] == 0

    def test_failures_exit_1(self, tmp_path):
        """6.3.2: Some checks fail → exit 1."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n\n**文件**: `src/missing.py`\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "1"],
            capture_output=True, text=True, cwd=root,
        )
        assert result.returncode == 1

    def test_missing_phase_ids_exit_2(self, tmp_path):
        """6.3.3: Missing --phase-ids → exit 2."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n#### 1.1 Create handler\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path],
            capture_output=True, text=True, cwd=root,
        )
        assert result.returncode == 2

    def test_unknown_phase_reported_as_scope_undetermined(self, tmp_path):
        """6.3.4: Unknown requested phase remains preview-only."""
        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n"
            "#### 1.1 Create handler\n"
        )
        cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [x] 1.1 Create handler\n"
        )
        fj_path, root = _setup_precheck_env(tmp_path, plan, cl)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--files-json", fj_path, "--phase-ids", "9"],
            capture_output=True, text=True, cwd=root,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["scopeUndeterminedPhaseIds"] == ["9"]
