"""Tests for review_plan.py fixers (Phase 4)."""
import os
import shutil
import tempfile
import pytest

TESTDATA = os.path.join(os.path.dirname(__file__), "testdata", "review")


def _copy_fixture(src_dir, tmp_path):
    """Copy fixture directory to tmp_path for safe modification."""
    dst = str(tmp_path / "work")
    shutil.copytree(src_dir, dst)
    return dst


# --- 4.1 fix_missing_sections (C-001) ---


class TestFixMissingSections:
    """fix_missing_sections(): insert missing checklist section headings."""

    def test_insert_one_section(self, tmp_path):
        from review_plan import fix_missing_sections, parse_checklist_sections, parse_plan_phases

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Foundation\n\n#### 1.1 A\n\n"
            "### Phase 2: Checks\n\n#### 2.1 B\n\n"
            "### Phase 3: Fixers\n\n#### 3.1 C\n"
        )
        # Checklist missing Phase 3
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Foundation\n\n- [ ] 1.1 A\n\n"
            "## Phase 2: Checks\n\n- [ ] 2.1 B\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_missing_sections(plan_path, cl_path)
        assert len(fixes) == 1
        assert fixes[0].id == "C-001"

        # Verify the section was inserted
        sections = parse_checklist_sections(cl_path)
        section_ids = [s["id"] for s in sections]
        assert "3" in section_ids

    def test_insert_multiple_sections(self, tmp_path):
        from review_plan import fix_missing_sections, parse_checklist_sections

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n\n"
            "### Phase 2: B\n\n#### 2.1 Y\n\n"
            "### Phase 3: C\n\n#### 3.1 Z\n\n"
            "### Phase 4: D\n\n#### 4.1 W\n"
        )
        # Only Phase 1 and Phase 3 exist
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [ ] 1.1 X\n\n"
            "## Phase 3: C\n\n- [ ] 3.1 Z\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_missing_sections(plan_path, cl_path)
        assert len(fixes) == 2

        sections = parse_checklist_sections(cl_path)
        section_ids = [s["id"] for s in sections]
        assert section_ids == ["1", "2", "3", "4"]

    def test_existing_content_preserved(self, tmp_path):
        from review_plan import fix_missing_sections, parse_checklist_items

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n\n"
            "### Phase 2: B\n\n#### 2.1 Y\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [x] 1.1 X\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_missing_sections(plan_path, cl_path)
        items = parse_checklist_items(cl_path)
        # Original item should still be checked
        item_1_1 = [i for i in items if i["id"] == "1.1"]
        assert len(item_1_1) == 1
        assert item_1_1[0]["checked"] is True

    def test_idempotent(self, tmp_path):
        from review_plan import fix_missing_sections

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n\n"
            "### Phase 2: B\n\n#### 2.1 Y\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [ ] 1.1 X\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes1 = fix_missing_sections(plan_path, cl_path)
        assert len(fixes1) == 1
        fixes2 = fix_missing_sections(plan_path, cl_path)
        assert len(fixes2) == 0  # idempotent


# --- 4.2 fix_numbering (C-003) ---


class TestFixNumbering:
    """fix_numbering(): re-number section items to be continuous."""

    def test_eliminate_gap(self, tmp_path):
        from review_plan import fix_numbering, parse_checklist_items

        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n"
            "- [ ] 1.1 First\n"
            "- [ ] 1.2 Second\n"
            "- [ ] 1.4 Fourth\n"
        )
        cl_path = str(tmp_path / "checklist.md")
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_numbering(cl_path)
        assert len(fixes) >= 1

        items = parse_checklist_items(cl_path)
        ids = [i["id"] for i in items]
        assert ids == ["1.1", "1.2", "1.3"]

    def test_preserve_checkbox_state(self, tmp_path):
        from review_plan import fix_numbering, parse_checklist_items

        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n"
            "- [x] 1.1 First\n"
            "- [ ] 1.3 Third\n"
        )
        cl_path = str(tmp_path / "checklist.md")
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_numbering(cl_path)
        items = parse_checklist_items(cl_path)
        assert items[0]["checked"] is True
        assert items[1]["checked"] is False
        assert items[1]["id"] == "1.2"

    def test_nested_numbering(self, tmp_path):
        """4.2.3: Preserve subsection nesting while filling numbering gaps."""
        from review_plan import fix_numbering, parse_checklist_items

        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n"
            "### 1.1 Parser\n\n"
            "- [ ] 1.1.1 First\n"
            "- [ ] 1.1.3 Third\n"
        )
        cl_path = str(tmp_path / "checklist.md")
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_numbering(cl_path)
        assert len(fixes) == 1

        items = parse_checklist_items(cl_path)
        ids = [i["id"] for i in items]
        assert ids == ["1.1.1", "1.1.2"]

    def test_idempotent(self, tmp_path):
        from review_plan import fix_numbering

        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n"
            "- [ ] 1.1 A\n- [ ] 1.3 B\n"
        )
        cl_path = str(tmp_path / "checklist.md")
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_numbering(cl_path)
        fixes2 = fix_numbering(cl_path)
        assert len(fixes2) == 0


# --- 4.3 fix_header_sync (C-004) ---


class TestFixHeaderSync:
    """fix_header_sync(): sync checklist header version/date to plan."""

    def test_sync_version(self, tmp_path):
        from review_plan import fix_header_sync, _parse_header

        plan = "# Plan\n\n> **版本**: 1.5\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
        checklist = "# CL\n\n> **版本**: 1.3\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_header_sync(plan_path, cl_path)
        assert len(fixes) >= 1

        cl_header = _parse_header(cl_path)
        assert cl_header["版本"] == "1.5"

    def test_sync_date(self, tmp_path):
        from review_plan import fix_header_sync, _parse_header

        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-09\n"
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-02-20\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_header_sync(plan_path, cl_path)
        cl_header = _parse_header(cl_path)
        assert cl_header["更新日期"] == "2026-03-09"

    def test_status_not_modified(self, tmp_path):
        from review_plan import fix_header_sync, _parse_header

        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: draft\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_header_sync(plan_path, cl_path)
        cl_header = _parse_header(cl_path)
        assert cl_header["状态"] == "draft"  # NOT changed

    def test_already_synced(self, tmp_path):
        from review_plan import fix_header_sync

        plan = "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
        checklist = "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_header_sync(plan_path, cl_path)
        assert len(fixes) == 0

    def test_idempotent(self, tmp_path):
        from review_plan import fix_header_sync

        plan = "# Plan\n\n> **版本**: 1.5\n> **状态**: active\n> **更新日期**: 2026-03-09\n"
        checklist = "# CL\n\n> **版本**: 1.3\n> **状态**: active\n> **更新日期**: 2026-02-20\n\n## Phase 1: X\n\n- [ ] 1.1 Y\n"
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_header_sync(plan_path, cl_path)
        fixes2 = fix_header_sync(plan_path, cl_path)
        assert len(fixes2) == 0


# --- 4.4 fix_missing_spec_ref (M-003) ---


class TestFixMissingSpecRef:
    """fix_missing_spec_ref(): add spec field to context.yaml."""

    def test_add_spec_unique_candidate(self, tmp_path):
        import yaml
        from review_plan import fix_missing_spec_ref

        ctx = {
            "apiVersion": "ferry.agent.context/v1alpha1",
            "kind": "PlanContext",
            "metadata": {"name": "test"},
            "spec": {
                "defaultTarget": "backend",
                "targets": {
                    "backend": {
                        "plan": "./implementation.md",
                        "checklist": "./implementation-checklist.md",
                    }
                }
            }
        }
        ctx_path = str(tmp_path / "context.yaml")
        with open(ctx_path, "w") as f:
            yaml.dump(ctx, f)
        # Create the candidate spec file
        spec_dir = tmp_path / ".." / ".." / "spec"
        os.makedirs(str(spec_dir), exist_ok=True)
        spec_path = str(spec_dir / "test-design.md")
        with open(spec_path, "w") as f:
            f.write("# Spec\n")

        fixes = fix_missing_spec_ref(ctx_path, "backend", str(spec_dir), "test")
        assert len(fixes) >= 1

        with open(ctx_path) as f:
            updated = yaml.safe_load(f)
        assert "spec" in updated["spec"]["targets"]["backend"]

    def test_multiple_candidates_no_fix(self, tmp_path):
        """4.4.2: Multiple spec candidates → no modification."""
        import yaml
        from review_plan import fix_missing_spec_ref

        ctx = {
            "apiVersion": "ferry.agent.context/v1alpha1",
            "kind": "PlanContext",
            "metadata": {"name": "test"},
            "spec": {
                "defaultTarget": "backend",
                "targets": {
                    "backend": {
                        "plan": "./implementation.md",
                        "checklist": "./implementation-checklist.md",
                    }
                }
            }
        }
        ctx_path = str(tmp_path / "context.yaml")
        with open(ctx_path, "w") as f:
            yaml.dump(ctx, f)
        spec_dir = tmp_path / "spec"
        os.makedirs(str(spec_dir), exist_ok=True)
        # Two candidates
        with open(str(spec_dir / "test-design.md"), "w") as f:
            f.write("# Spec 1\n")
        with open(str(spec_dir / "test-api.md"), "w") as f:
            f.write("# Spec 2\n")

        fixes = fix_missing_spec_ref(ctx_path, "backend", str(spec_dir), "test")
        assert len(fixes) == 0

    def test_already_has_spec(self, tmp_path):
        import yaml
        from review_plan import fix_missing_spec_ref

        ctx = {
            "apiVersion": "ferry.agent.context/v1alpha1",
            "kind": "PlanContext",
            "metadata": {"name": "test"},
            "spec": {
                "defaultTarget": "backend",
                "targets": {
                    "backend": {
                        "plan": "./implementation.md",
                        "checklist": "./implementation-checklist.md",
                        "spec": "../../spec/test-design.md",
                    }
                }
            }
        }
        ctx_path = str(tmp_path / "context.yaml")
        with open(ctx_path, "w") as f:
            yaml.dump(ctx, f)

        fixes = fix_missing_spec_ref(ctx_path, "backend", str(tmp_path), "test")
        assert len(fixes) == 0

    def test_yaml_still_parseable(self, tmp_path):
        import yaml
        from review_plan import fix_missing_spec_ref

        ctx = {
            "apiVersion": "ferry.agent.context/v1alpha1",
            "kind": "PlanContext",
            "metadata": {"name": "test"},
            "spec": {
                "defaultTarget": "backend",
                "targets": {
                    "backend": {
                        "plan": "./implementation.md",
                        "checklist": "./implementation-checklist.md",
                    }
                }
            }
        }
        ctx_path = str(tmp_path / "context.yaml")
        with open(ctx_path, "w") as f:
            yaml.dump(ctx, f)
        spec_dir = tmp_path / "spec"
        os.makedirs(str(spec_dir), exist_ok=True)
        with open(str(spec_dir / "test-design.md"), "w") as f:
            f.write("# Spec\n")

        fix_missing_spec_ref(ctx_path, "backend", str(spec_dir), "test")
        # Should not raise
        with open(ctx_path) as f:
            data = yaml.safe_load(f)
        assert data is not None


# --- 4.5 Stub generation (C-002/M-001) ---


class TestFixStubGeneration:
    """fix_stubs(): generate checklist item stubs for orphan plan tasks."""

    def test_generate_stub(self, tmp_path):
        from review_plan import fix_stubs, parse_checklist_items

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: Test\n\n#### 1.1 First\n\n#### 1.2 Second\n\n#### 1.3 Third\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: Test\n\n- [ ] 1.1 First\n- [ ] 1.2 Second\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fixes = fix_stubs(plan_path, cl_path)
        assert len(fixes) >= 1

        items = parse_checklist_items(cl_path)
        item_ids = [i["id"] for i in items]
        assert "1.3" in item_ids

    def test_correct_section_placement(self, tmp_path):
        from review_plan import fix_stubs, parse_checklist_items

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n\n"
            "### Phase 2: B\n\n#### 2.1 Y\n\n#### 2.2 Z\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [ ] 1.1 X\n\n"
            "## Phase 2: B\n\n- [ ] 2.1 Y\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_stubs(plan_path, cl_path)
        items = parse_checklist_items(cl_path)
        # 2.2 should be in section 2
        stub = [i for i in items if i["id"] == "2.2"]
        assert len(stub) == 1
        assert stub[0]["section_id"] == "2"

    def test_preserve_existing_items(self, tmp_path):
        from review_plan import fix_stubs, parse_checklist_items

        plan = (
            "# Plan\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n"
            "> **执行模式**: sequential\n\n"
            "### Phase 1: A\n\n#### 1.1 X\n\n#### 1.2 Y\n"
        )
        checklist = (
            "# CL\n\n> **版本**: 1.0\n> **状态**: active\n> **更新日期**: 2026-03-01\n\n"
            "## Phase 1: A\n\n- [x] 1.1 X\n"
        )
        plan_path = str(tmp_path / "plan.md")
        cl_path = str(tmp_path / "checklist.md")
        with open(plan_path, "w") as f:
            f.write(plan)
        with open(cl_path, "w") as f:
            f.write(checklist)

        fix_stubs(plan_path, cl_path)
        items = parse_checklist_items(cl_path)
        original = [i for i in items if i["id"] == "1.1"]
        assert original[0]["checked"] is True
