"""Tests for review_plan.py checkers (Phase 2-3)."""
import os
import json
import tempfile
import pytest

TESTDATA = os.path.join(os.path.dirname(__file__), "testdata", "review")


def _make_files_json(files_dict, tmpdir):
    """Create a files-json file from a dict of {role: path}."""
    files = [{"role": role, "path": os.path.abspath(path)} for role, path in files_dict.items()]
    path = os.path.join(tmpdir, "files.json")
    with open(path, "w") as f:
        json.dump({"files": files}, f)
    return path


def _build_context(plan_dir, tmpdir, extra_roles=None):
    """Build standard context dict from a fixture directory."""
    files_dict = {
        "plan": os.path.join(plan_dir, "plan.md"),
        "checklist": os.path.join(plan_dir, "checklist.md"),
    }
    if os.path.exists(os.path.join(plan_dir, "spec.md")):
        files_dict["spec"] = os.path.join(plan_dir, "spec.md")
    if os.path.exists(os.path.join(plan_dir, "test-checklist.md")):
        files_dict["test-checklist"] = os.path.join(plan_dir, "test-checklist.md")
    if extra_roles:
        files_dict.update(extra_roles)
    return files_dict


# --- Phase 2: C-series Consistency Checks ---


class TestC001SectionAlignment:
    """C-001: Plan phase → checklist section alignment."""

    def test_aligned(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c001 = [v for v in violations if v.id == "C-001"]
        assert len(c001) == 0

    def test_missing_section(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        # Create a checklist missing one section
        checklist = (
            "# Checklist\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## W0: 基础设施准备 [config]\n\n- [ ] W0.1 Item\n\n"
            "## W1.Auth: 认证层实现 [apiserver-auth]\n\n- [ ] W1.Auth.1 Item\n\n"
            # Missing W1.Config and W2.Service sections
        )
        cl_path = str(tmp_path / "checklist.md")
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {
            "plan": os.path.join(plan_dir, "plan.md"),
            "checklist": cl_path,
        }
        violations = check_consistency(files)
        c001 = [v for v in violations if v.id == "C-001"]
        assert len(c001) == 2  # W1.Config and W2.Service missing
        assert all(v.severity == "error" for v in c001)
        assert all(v.auto_fixable is True for v in c001)

    def test_legacy_numbered_sequential_section_is_accepted(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### 3.1 Phase 1: Foundation\n\n#### 3.1.1 Build foundation\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## 1 Phase 1: Foundation\n\n- [ ] 1.1 Build foundation\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        plan_path_obj = tmp_path / "plan.md"
        cl_path_obj = tmp_path / "checklist.md"
        plan_path_obj.write_text(plan, encoding="utf-8")
        cl_path_obj.write_text(checklist, encoding="utf-8")
        violations = check_consistency({"plan": plan_path, "checklist": cl_path})
        c001 = [v for v in violations if v.id == "C-001"]
        assert len(c001) == 0


class TestC002OrphanCheck:
    """C-002: Checklist item ID ↔ plan task heading bidirectional orphan check."""

    def test_all_match(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c002 = [v for v in violations if v.id == "C-002"]
        assert len(c002) == 0

    def test_orphan_checklist_item(self, tmp_path):
        from review_plan import build_review_result

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### Phase 1: Test\n\n#### 1.1 Task one\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n- [ ] 1.1 Task one\n- [ ] 1.8 Orphan item\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        review = build_review_result(files)
        c002 = [v for v in review["violations"] if v.id == "C-002"]
        assert len(c002) == 0
        assert review["summary"]["semantic_pending"] == 1
        assert len(review["semantic_pending"]) == 1
        assert review["semantic_pending"][0]["id"] == "S-004"
        assert review["semantic_pending"][0]["checklist_ref"] == "1.8"

    def test_legacy_full_task_number_matches_phase_local_checklist_item(self, tmp_path):
        from review_plan import build_review_result

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### 4.1 Phase 1: Test\n\n#### 4.1.1 Task one\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## 1 Phase 1: Test\n\n- [ ] 1.1 Task one\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")

        review = build_review_result({"plan": plan_path, "checklist": cl_path})
        c002 = [v for v in review["violations"] if v.id == "C-002"]
        m001 = [v for v in review["violations"] if v.id == "M-001"]
        assert len(c002) == 0
        assert len(m001) == 0

    def test_detail_checkboxes_under_subsection_are_not_parsed_as_task_ids(self, tmp_path):
        from review_plan import build_review_result, parse_checklist_task_refs

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### 3.2 Phase 2: Loader\n\n"
            "#### 3.2.1 Add constants\n\n"
            "#### 3.2.2 Split env handlers\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## 2 Phase 2: Loader\n\n"
            "### 2.1 Add constants\n\n"
            "- [x] 添加 `EnvArchiverUser` 常量\n"
            "- [x] 添加 `EnvArchiverPassword` 常量\n\n"
            "### 2.2 Split env handlers\n\n"
            "- [x] 实现 `ApplyExternalEnvVars`\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")

        refs = parse_checklist_task_refs(cl_path)
        assert [ref["id"] for ref in refs] == ["2.1", "2.2"]

        review = build_review_result({"plan": plan_path, "checklist": cl_path})
        c002 = [v for v in review["violations"] if v.id == "C-002"]
        m001 = [v for v in review["violations"] if v.id == "M-001"]
        s004 = [item for item in review["semantic_pending"] if item["id"] == "S-004"]
        assert len(c002) == 0
        assert len(m001) == 0
        assert len(s004) == 0


class TestSemanticPending:
    """Semantic pending items that require LLM content review."""

    def test_spec_sections_trigger_s001(self, tmp_path):
        from review_plan import build_review_result

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n#### 1.1 Build foundation\n\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 Build foundation\n"
        )
        spec = (
            "# Spec\n\n> **版本**: 1.0\n> **状态**: draft\n> **更新日期**: 2026-03-01\n\n"
            "## 1 概述\n\nOverview.\n\n"
            "## 2 交互流程\n\nWorkflow details.\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        spec_path = str(tmp_path / "spec.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")
        (tmp_path / "spec.md").write_text(spec, encoding="utf-8")

        review = build_review_result({
            "plan": plan_path,
            "checklist": cl_path,
            "spec": spec_path,
        })

        ids = [item["id"] for item in review["semantic_pending"]]
        assert "S-001" in ids

    def test_spec_error_paths_trigger_s002(self, tmp_path):
        from review_plan import build_review_result

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Validation\n\n#### 1.1 Add validation\n\n"
            "## 验收标准\n\nDone.\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Validation\n\n- [ ] 1.1 Add validation\n"
        )
        spec = (
            "# Spec\n\n> **版本**: 1.0\n> **状态**: draft\n> **更新日期**: 2026-03-01\n\n"
            "## 1 错误处理\n\n"
            "请求 invalid 时返回错误；服务超时后必须回滚。\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        spec_path = str(tmp_path / "spec.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")
        (tmp_path / "spec.md").write_text(spec, encoding="utf-8")

        review = build_review_result({
            "plan": plan_path,
            "checklist": cl_path,
            "spec": spec_path,
        })

        ids = [item["id"] for item in review["semantic_pending"]]
        assert "S-002" in ids

    def test_description_mismatch_triggers_s003(self, tmp_path):
        from review_plan import build_review_result

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Security\n\n"
            "#### 1.1 Enforce RBAC on cluster detail endpoint\n\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Security\n\n"
            "- [ ] 1.1 Add loading skeleton for cluster detail page\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")

        review = build_review_result({
            "plan": plan_path,
            "checklist": cl_path,
        })

        s003 = [item for item in review["semantic_pending"] if item["id"] == "S-003"]
        assert len(s003) == 1
        assert s003[0]["checklist_ref"] == "1.1"


class TestC003Numbering:
    """C-003: Section item numbering continuity."""

    def test_continuous(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c003 = [v for v in violations if v.id == "C-003"]
        assert len(c003) == 0

    def test_gap(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### Phase 1: Test\n\n#### 1.1 A\n\n#### 1.2 B\n\n#### 1.4 D\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n- [ ] 1.1 A\n- [ ] 1.2 B\n- [ ] 1.4 D\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_consistency(files)
        c003 = [v for v in violations if v.id == "C-003"]
        assert len(c003) >= 1
        assert c003[0].severity == "warning"
        assert c003[0].auto_fixable is True


class TestC004HeaderSync:
    """C-004: Plan/checklist header version/date sync."""

    def test_matching(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c004 = [v for v in violations if v.id == "C-004"]
        assert len(c004) == 0

    def test_version_drift(self, tmp_path):
        from review_plan import check_consistency

        plan = "# Plan\n\n> **版本**: 1.5\n> **状态**: active\n> **更新日期**: 2026-03-01\n> **执行模式**: sequential\n\n### Phase 1: X\n\n#### 1.1 Y\n"
        checklist = "# CL\n\n> **版本**: 1.3\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_consistency(files)
        c004 = [v for v in violations if v.id == "C-004"]
        assert len(c004) >= 1
        assert any(v.auto_fixable is True for v in c004)

    def test_status_drift(self, tmp_path):
        from review_plan import check_consistency

        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n> **执行模式**: sequential\n\n### Phase 1: X\n\n#### 1.1 Y\n"
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: draft\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_consistency(files)
        c004 = [v for v in violations if v.id == "C-004"]
        status_v = [v for v in c004 if "状态" in v.message or "status" in v.message.lower()]
        assert len(status_v) >= 1
        assert all(v.auto_fixable is False for v in status_v)


class TestC005AgentRole:
    """C-005: Parallel plan agent role validation."""

    def test_valid_role(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        agents_path = os.path.join(plan_dir, "agents.md")
        # Create agents.md with valid roles
        with open(agents_path, "w") as f:
            f.write("## 6.1\n| 角色 ID | 角色 |\n|---|---|\n| config | Config |\n| apiserver-auth | Auth |\n| apiserver-infra | Infra |\n| apiserver-service | Service |\n")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files, agent_md_path=agents_path)
        c005 = [v for v in violations if v.id == "C-005"]
        assert len(c005) == 0
        os.unlink(agents_path)

    def test_invalid_role(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        agents_path = str(tmp_path / "agents.md")
        with open(agents_path, "w") as f:
            f.write("## 6.1\n| 角色 ID | 角色 |\n|---|---|\n| config | Config |\n")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files, agent_md_path=agents_path)
        c005 = [v for v in violations if v.id == "C-005"]
        assert len(c005) >= 1
        assert c005[0].severity == "error"

    def test_skip_sequential(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c005 = [v for v in violations if v.id == "C-005"]
        assert len(c005) == 0


class TestC006DependsOn:
    """C-006: depends-on reference validation."""

    def test_valid(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c006 = [v for v in violations if v.id == "C-006"]
        assert len(c006) == 0

    def test_dangling(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: parallel\n\n"
            "### W1.Auth: Auth\n<!-- agent: auth -->\n<!-- depends-on: W9.Missing -->\n\n"
            "#### W1.Auth.1 Item\n"
        )
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## W1.Auth: Auth [auth]\n\n- [ ] W1.Auth.1 Item\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_consistency(files)
        c006 = [v for v in violations if v.id == "C-006"]
        assert len(c006) >= 1
        assert c006[0].severity == "error"


class TestC007FilesMeta:
    """C-007: files metadata existence check."""

    def test_present(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c007 = [v for v in violations if v.id == "C-007"]
        assert len(c007) == 0

    def test_missing(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: parallel\n\n"
            "### W1.Auth: Auth\n<!-- agent: auth -->\n<!-- depends-on: — -->\n"
            "<!-- no files metadata -->\n\n#### W1.Auth.1 Item\n"
        )
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## W1.Auth: Auth [auth]\n\n- [ ] W1.Auth.1 Item\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_consistency(files)
        c007 = [v for v in violations if v.id == "C-007"]
        assert len(c007) >= 1
        assert c007[0].severity == "error"


class TestC008PhaseMapping:
    """C-008: test-checklist phase-mapping validation."""

    def test_valid(self, tmp_path):
        from review_plan import check_consistency

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_consistency(files)
        c008 = [v for v in violations if v.id == "C-008"]
        assert len(c008) == 0

    def test_invalid_mapping(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### Phase 1: Test\n\n#### 1.1 A\n"
        )
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: Test\n\n- [ ] 1.1 A\n"
        test_cl = "# TCL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## 1 Tests\n<!-- phase-mapping: W9.None -->\n\n- [ ] 1.1 Test\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        tcl_path = str(tmp_path / "test-checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        with open(tcl_path, "w") as f:
            f.write(test_cl)
        files = {"plan": plan_path, "checklist": cl_path, "test-checklist": tcl_path}
        violations = check_consistency(files)
        c008 = [v for v in violations if v.id == "C-008"]
        assert len(c008) >= 1
        assert c008[0].severity == "warning"
        assert "test-checklist mapping" in c008[0].message

    def test_heading_based_mapping_is_valid_without_comment(self, tmp_path):
        from review_plan import check_consistency

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "### Phase 1: Test\n\n#### 1.1 A\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n- [ ] 1.1 A\n"
        )
        test_cl = (
            "# TCL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Tests\n\n- [ ] 1.1 Test\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        tcl_path = str(tmp_path / "test-checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        with open(tcl_path, "w") as f:
            f.write(test_cl)
        files = {"plan": plan_path, "checklist": cl_path, "test-checklist": tcl_path}
        violations = check_consistency(files)
        c008 = [v for v in violations if v.id == "C-008"]
        assert len(c008) == 0


# --- Phase 3: M/B-series Checks ---


class TestM001TaskCoverage:
    """M-001: Plan task → checklist item coverage."""

    def test_all_covered(self, tmp_path):
        from review_plan import check_completeness

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_completeness(files)
        m001 = [v for v in violations if v.id == "M-001"]
        assert len(m001) == 0

    def test_missing_item(self, tmp_path):
        from review_plan import check_completeness

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### Phase 1: Test\n\n#### 1.1 A\n\n#### 1.2 B\n\n#### 1.3 C\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n- [ ] 1.1 A\n- [ ] 1.2 B\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_completeness(files)
        m001 = [v for v in violations if v.id == "M-001"]
        assert len(m001) >= 1
        assert m001[0].severity == "error"

    def test_subsection_heading_counts_as_task_coverage(self, tmp_path):
        from review_plan import check_completeness

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### 3.2 Phase 2: Refactor loader\n\n"
            "#### 3.2.1 Add env constants\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## 2 Phase 2: Refactor loader\n\n### 2.1 Add env constants\n\n"
            "- [ ] Add EnvArchiverUser\n- [ ] Add EnvArchiverPassword\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
        (tmp_path / "checklist.md").write_text(checklist, encoding="utf-8")

        violations = check_completeness({"plan": plan_path, "checklist": cl_path})
        m001 = [v for v in violations if v.id == "M-001"]
        assert len(m001) == 0


class TestM002MappingCoverage:
    """M-002: test-checklist phase-mapping coverage."""

    def test_full_coverage(self, tmp_path):
        from review_plan import check_completeness

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_completeness(files)
        m002 = [v for v in violations if v.id == "M-002"]
        # W0 has no test mapping
        assert len(m002) >= 1

    def test_skip_without_test_checklist(self, tmp_path):
        from review_plan import check_completeness

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = {"plan": os.path.join(plan_dir, "plan.md"), "checklist": os.path.join(plan_dir, "checklist.md")}
        violations = check_completeness(files)
        m002 = [v for v in violations if v.id == "M-002"]
        assert len(m002) == 0


class TestM003SpecField:
    """M-003: context.yaml spec field."""

    def test_present(self, tmp_path):
        from review_plan import check_completeness

        files = {
            "plan": os.path.join(TESTDATA, "minimal-valid", "plan.md"),
            "checklist": os.path.join(TESTDATA, "minimal-valid", "checklist.md"),
            "spec": os.path.join(TESTDATA, "parallel-plan", "spec.md"),
        }
        violations = check_completeness(files, context_yaml_path=str(tmp_path / "ctx.yaml"))
        m003 = [v for v in violations if v.id == "M-003"]
        assert len(m003) == 0

    def test_missing(self, tmp_path):
        from review_plan import check_completeness

        files = {
            "plan": os.path.join(TESTDATA, "minimal-valid", "plan.md"),
            "checklist": os.path.join(TESTDATA, "minimal-valid", "checklist.md"),
        }
        violations = check_completeness(files, context_yaml_path=str(tmp_path / "ctx.yaml"))
        m003 = [v for v in violations if v.id == "M-003"]
        assert len(m003) >= 1
        assert m003[0].severity == "warning"
        assert m003[0].auto_fixable is False

    def test_missing_unique_candidate_auto_fixable(self, tmp_path):
        from review_plan import check_completeness

        docs_root = tmp_path / "docs"
        plan_dir = docs_root / "plan" / "demo"
        spec_dir = docs_root / "spec"
        plan_dir.mkdir(parents=True)
        spec_dir.mkdir(parents=True)

        plan_path = plan_dir / "implementation.md"
        checklist_path = plan_dir / "implementation-checklist.md"
        context_path = plan_dir / "context.yaml"
        spec_path = spec_dir / "demo-design.md"

        plan_path.write_text(
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n### Phase 1: Demo\n\n#### 1.1 Task\n",
            encoding="utf-8",
        )
        checklist_path.write_text(
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Demo\n\n- [ ] 1.1 Task\n",
            encoding="utf-8",
        )
        context_path.write_text(
            "apiVersion: ferry.agent.context/v1alpha1\n"
            "kind: PlanContext\n"
            "metadata:\n"
            "  name: demo\n"
            "spec:\n"
            "  defaultTarget: backend\n"
            "  targets:\n"
            "    backend:\n"
            "      plan: ./implementation.md\n"
            "      checklist: ./implementation-checklist.md\n",
            encoding="utf-8",
        )
        spec_path.write_text("# Spec\n", encoding="utf-8")

        files = {
            "plan": str(plan_path),
            "checklist": str(checklist_path),
        }
        violations = check_completeness(files, context_yaml_path=str(context_path))
        m003 = [v for v in violations if v.id == "M-003"]
        assert len(m003) == 1
        assert m003[0].auto_fixable is True


class TestB001ItemCount:
    """B-001: Section item count range."""

    def test_normal(self, tmp_path):
        from review_plan import check_best_practice

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_best_practice(files)
        b001 = [v for v in violations if v.id == "B-001"]
        assert len(b001) == 0

    def test_too_few(self, tmp_path):
        from review_plan import check_best_practice

        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Only item\n"
        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n> **执行模式**: sequential\n\n### Phase 1: X\n\n#### 1.1 Only\n"
        cl_path = str(tmp_path / "checklist.md")
        plan_path = str(tmp_path / "plan.md")
        with open(cl_path, "w") as f:
            f.write(checklist)
        with open(plan_path, "w") as f:
            f.write(plan)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_best_practice(files)
        b001 = [v for v in violations if v.id == "B-001"]
        assert len(b001) >= 1
        assert b001[0].severity == "advisory"


class TestB002DagAcyclicity:
    """B-002: Parallel plan DAG acyclicity."""

    def test_acyclic(self, tmp_path):
        from review_plan import check_best_practice

        plan_dir = os.path.join(TESTDATA, "parallel-plan")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_best_practice(files)
        b002 = [v for v in violations if v.id == "B-002"]
        assert len(b002) == 0

    def test_cycle(self, tmp_path):
        from review_plan import check_best_practice

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: parallel\n\n"
            "### W1.A: A\n<!-- agent: a -->\n<!-- files: a/** -->\n<!-- depends-on: W2.B -->\n\n"
            "#### W1.A.1 Item\n\n"
            "### W2.B: B\n<!-- agent: b -->\n<!-- files: b/** -->\n<!-- depends-on: W1.A -->\n\n"
            "#### W2.B.1 Item\n"
        )
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## W1.A: A [a]\n\n- [ ] W1.A.1 Item\n\n## W2.B: B [b]\n\n- [ ] W2.B.1 Item\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_best_practice(files)
        b002 = [v for v in violations if v.id == "B-002"]
        assert len(b002) >= 1
        assert b002[0].severity == "error"

    def test_skip_sequential(self, tmp_path):
        from review_plan import check_best_practice

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_best_practice(files)
        b002 = [v for v in violations if v.id == "B-002"]
        assert len(b002) == 0


class TestB003AcceptanceCriteria:
    """B-003: Plan acceptance criteria section."""

    def test_present(self, tmp_path):
        from review_plan import check_best_practice

        plan_dir = os.path.join(TESTDATA, "minimal-valid")
        files = _build_context(plan_dir, str(tmp_path))
        violations = check_best_practice(files)
        b003 = [v for v in violations if v.id == "B-003"]
        assert len(b003) == 0

    def test_missing(self, tmp_path):
        from review_plan import check_best_practice

        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n> **执行模式**: sequential\n\n### Phase 1: X\n\n#### 1.1 A\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write("# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 A\n")
        files = {"plan": plan_path, "checklist": cl_path}
        violations = check_best_practice(files)
        b003 = [v for v in violations if v.id == "B-003"]
        assert len(b003) >= 1
        assert b003[0].severity == "advisory"
