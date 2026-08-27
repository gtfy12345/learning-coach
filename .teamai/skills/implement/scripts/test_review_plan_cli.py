"""Tests for review_plan.py CLI behavior (Phase 5)."""
import json
import subprocess
import sys


SCRIPT = __file__.replace("test_review_plan_cli.py", "review_plan.py")
PYTHON = sys.executable


def _make_files_json(tmp_path, plan_content=None, cl_content=None, spec_content=None):
    """Create plan/checklist/spec plus files.json for CLI tests."""
    import yaml

    if plan_content is None:
        plan_content = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n#### 1.1 A\n\n"
            "## 验收标准\n\nDone.\n"
        )
    if cl_content is None:
        cl_content = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 A\n"
        )

    plan_path = str(tmp_path / "plan.md")
    cl_path = str(tmp_path / "checklist.md")
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(plan_content)
    with open(cl_path, "w", encoding="utf-8") as f:
        f.write(cl_content)

    spec_path = None
    if spec_content is not None:
        spec_path = str(tmp_path / "spec.md")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(spec_content)

    ctx = {
        "apiVersion": "ferry.agent.context/v1alpha1",
        "kind": "PlanContext",
        "metadata": {"name": "test"},
        "spec": {
            "defaultTarget": "backend",
            "targets": {
                "backend": {
                    "plan": "./plan.md",
                    "checklist": "./checklist.md",
                    "spec": "../../spec/test-design.md",
                }
            }
        }
    }
    ctx_path = str(tmp_path / "context.yaml")
    with open(ctx_path, "w", encoding="utf-8") as f:
        yaml.dump(ctx, f)

    files_json = {
        "files": [
            {"role": "plan", "path": plan_path},
            {"role": "checklist", "path": cl_path},
        ]
    }
    if spec_path:
        files_json["files"].append({"role": "spec", "path": spec_path})
    fj_path = str(tmp_path / "files.json")
    with open(fj_path, "w", encoding="utf-8") as f:
        json.dump(files_json, f)

    return ctx_path, fj_path


class TestCli:
    """CLI main() tests."""

    def test_check_mode(self, tmp_path):
        ctx_path, fj_path = _make_files_json(tmp_path)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode in (0, 1)
        assert "total:" in result.stdout.lower() or "summary" in result.stdout.lower()

    def test_fix_mode(self, tmp_path):
        ctx_path, fj_path = _make_files_json(tmp_path)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--fix"],
            capture_output=True, text=True,
        )
        assert result.returncode in (0, 1)
        assert "Applied" in result.stdout or "Post-fix" in result.stdout or result.returncode == 0

    def test_missing_required_arg(self, tmp_path):
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", str(tmp_path / "none.yaml")],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_check_fix_mutual_exclusion(self, tmp_path):
        ctx_path, fj_path = _make_files_json(tmp_path)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--check", "--fix"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2

    def test_fix_json_ignores_json(self, tmp_path):
        ctx_path, fj_path = _make_files_json(tmp_path)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--fix", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode in (0, 1)
        try:
            json.loads(result.stdout)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json or "Applied" in result.stdout

    def test_exit_code_semantics(self, tmp_path):
        import yaml

        clean_plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n#### 1.1 A\n\n#### 1.2 B\n\n"
            "## 验收标准\n\nDone.\n"
        )
        clean_cl = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 A\n- [ ] 1.2 B\n"
        )
        clean_dir = tmp_path / "clean"
        clean_dir.mkdir()
        plan_path = str(clean_dir / "plan.md")
        cl_path = str(clean_dir / "checklist.md")
        spec_path = str(clean_dir / "spec.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(clean_plan)
        with open(cl_path, "w", encoding="utf-8") as f:
            f.write(clean_cl)
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write("# Spec\n")
        ctx = {
            "apiVersion": "ferry.agent.context/v1alpha1",
            "kind": "PlanContext",
            "metadata": {"name": "test"},
            "spec": {"defaultTarget": "backend",
                     "targets": {"backend": {"plan": "./plan.md",
                                             "checklist": "./checklist.md",
                                             "spec": "./spec.md"}}}
        }
        ctx_path = str(clean_dir / "context.yaml")
        with open(ctx_path, "w", encoding="utf-8") as f:
            yaml.dump(ctx, f)
        fj = {"files": [
            {"role": "plan", "path": plan_path},
            {"role": "checklist", "path": cl_path},
            {"role": "spec", "path": spec_path},
        ]}
        fj_path = str(clean_dir / "files.json")
        with open(fj_path, "w", encoding="utf-8") as f:
            json.dump(fj, f)

        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

        plan_with_issue = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n#### 1.2 X2\n\n"
            "### Phase 2: B\n\n#### 2.1 Y\n#### 2.2 Y2\n\n"
            "## 验收标准\n\nDone.\n"
        )
        cl_missing = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [ ] 1.1 X\n- [ ] 1.2 X2\n"
        )
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(plan_with_issue)
        with open(cl_path, "w", encoding="utf-8") as f:
            f.write(cl_missing)
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1

    def test_spec_semantic_pending_sets_exit_code(self, tmp_path):
        ctx_path, fj_path = _make_files_json(
            tmp_path,
            spec_content=(
                "# Spec\n\n> **版本**: 1.0\n> **状态**: draft\n> **更新日期**: 2026-03-01\n\n"
                "## 1 Overview\n\nSomething.\n\n"
                "## 2 Error Handling\n\nInvalid input returns an error.\n"
            ),
        )
        result = subprocess.run(
            [PYTHON, SCRIPT, "--context", ctx_path, "--target", "backend",
             "--files-json", fj_path, "--check"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "S-001" in result.stdout or "semantic" in result.stdout.lower()
