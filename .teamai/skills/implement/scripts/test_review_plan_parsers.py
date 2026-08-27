"""Tests for review_plan.py data models and parsers (Phase 1)."""
import os
import pytest

TESTDATA = os.path.join(os.path.dirname(__file__), "testdata", "review")

# --- 1.1 Data models & constants ---


class TestDataModels:
    """Tests for Violation/Fix dataclasses and constants."""

    def test_violation_fields(self):
        from review_plan import Violation

        v = Violation(
            id="C-001",
            category="consistency",
            severity="error",
            message="test message",
            auto_fixable=True,
            file="checklist.md",
            plan_ref="Phase 1",
            checklist_ref=None,
        )
        assert v.id == "C-001"
        assert v.category == "consistency"
        assert v.severity == "error"
        assert v.message == "test message"
        assert v.auto_fixable is True
        assert v.file == "checklist.md"
        assert v.plan_ref == "Phase 1"
        assert v.checklist_ref is None

    def test_fix_fields(self):
        from review_plan import Fix

        f = Fix(
            id="C-001",
            action="add_section",
            file="checklist.md",
            description="Insert section heading",
            diff_preview="+ ## Phase 3: ...",
        )
        assert f.id == "C-001"
        assert f.action == "add_section"
        assert f.file == "checklist.md"
        assert f.description == "Insert section heading"
        assert f.diff_preview == "+ ## Phase 3: ..."

    def test_severity_constants(self):
        from review_plan import SEV_ERROR, SEV_WARNING, SEV_ADVISORY

        assert SEV_ERROR == "error"
        assert SEV_WARNING == "warning"
        assert SEV_ADVISORY == "advisory"

    def test_check_id_constants_c_series(self):
        from review_plan import (
            C_001, C_002, C_003, C_004,
            C_005, C_006, C_007, C_008,
        )

        assert C_001 == "C-001"
        assert C_002 == "C-002"
        assert C_003 == "C-003"
        assert C_004 == "C-004"
        assert C_005 == "C-005"
        assert C_006 == "C-006"
        assert C_007 == "C-007"
        assert C_008 == "C-008"

    def test_check_id_constants_m_series(self):
        from review_plan import M_001, M_002, M_003

        assert M_001 == "M-001"
        assert M_002 == "M-002"
        assert M_003 == "M-003"

    def test_check_id_constants_b_series(self):
        from review_plan import B_001, B_002, B_003

        assert B_001 == "B-001"
        assert B_002 == "B-002"
        assert B_003 == "B-003"

    def test_violation_default_optional_fields(self):
        from review_plan import Violation

        v = Violation(
            id="C-001",
            category="consistency",
            severity="error",
            message="msg",
        )
        assert v.auto_fixable is False
        assert v.file is None
        assert v.plan_ref is None
        assert v.checklist_ref is None


# --- 1.2 parse_plan_phases ---


class TestParsePlanPhases:
    """Tests for parse_plan_phases()."""

    def test_parallel_plan(self):
        from review_plan import parse_plan_phases

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        phases = parse_plan_phases(path)
        assert len(phases) == 4
        # W0
        assert phases[0]["id"] == "W0"
        assert phases[0]["title"] == "基础设施准备"
        assert phases[0]["agent"] == "config"
        assert phases[0]["depends_on"] == []
        assert "config/**" in phases[0]["files_globs"]
        # W1.Auth
        assert phases[1]["id"] == "W1.Auth"
        assert phases[1]["title"] == "认证层实现"
        assert phases[1]["agent"] == "apiserver-auth"
        assert phases[1]["depends_on"] == ["W0"]
        # W2.Service
        assert phases[3]["id"] == "W2.Service"
        assert phases[3]["depends_on"] == ["W1.Auth", "W1.Config"]

    def test_sequential_plan(self):
        from review_plan import parse_plan_phases

        path = os.path.join(TESTDATA, "minimal-valid", "plan.md")
        phases = parse_plan_phases(path)
        assert len(phases) == 2
        assert phases[0]["id"] == "1"
        assert phases[0]["title"] == "Foundation"
        assert phases[0]["agent"] is None
        assert phases[0]["depends_on"] == []
        assert phases[1]["id"] == "2"
        assert phases[1]["title"] == "Checks"

    def test_empty_plan(self):
        """Plan with no phase headings returns empty list."""
        from review_plan import parse_plan_phases
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Empty Plan\n\nNo phases here.\n")
            f.flush()
            phases = parse_plan_phases(f.name)
        os.unlink(f.name)
        assert phases == []

    def test_metadata_missing(self):
        """Phase heading without metadata comments → agent/files are None/empty."""
        from review_plan import parse_plan_phases

        path = os.path.join(TESTDATA, "minimal-valid", "plan.md")
        phases = parse_plan_phases(path)
        for p in phases:
            assert p["agent"] is None
            assert p["files_globs"] == []


# --- 1.3 parse_plan_file_declarations ---


class TestParsePlanFileDeclarations:
    """Tests for parse_plan_file_declarations()."""

    def test_phase_level_files(self):
        from review_plan import parse_plan_file_declarations

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        decls = parse_plan_file_declarations(path)
        phase_meta = [d for d in decls if d["source"] == "phase_metadata"]
        assert len(phase_meta) > 0
        assert any(d["glob"] == "config/**" for d in phase_meta)

    def test_task_level_files(self):
        from review_plan import parse_plan_file_declarations

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        decls = parse_plan_file_declarations(path)
        task_decls = [d for d in decls if d["source"] == "task_declaration"]
        assert any(d["exact_path"] == "config/base.yaml" for d in task_decls)
        assert any(d["exact_path"] == "internal/auth/password.go" for d in task_decls)

    def test_multi_glob(self):
        from review_plan import parse_plan_file_declarations

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        decls = parse_plan_file_declarations(path)
        # W1.Auth has <!-- files: internal/auth/**, internal/auth/password.go -->
        auth_phase = [d for d in decls if d.get("phase_id") == "W1.Auth" and d["source"] == "phase_metadata"]
        assert len(auth_phase) == 2

    def test_no_declarations(self):
        from review_plan import parse_plan_file_declarations
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Plan\n\nNo file declarations.\n")
            f.flush()
            decls = parse_plan_file_declarations(f.name)
        os.unlink(f.name)
        assert decls == []


# --- 1.4 parse_checklist_sections and parse_checklist_items ---


class TestParseChecklistSections:
    """Tests for parse_checklist_sections()."""

    def test_parallel_format(self):
        from review_plan import parse_checklist_sections

        path = os.path.join(TESTDATA, "parallel-plan", "checklist.md")
        sections = parse_checklist_sections(path)
        assert len(sections) == 4
        assert sections[0]["id"] == "W0"
        assert sections[1]["id"] == "W1.Auth"
        assert len(sections[1]["items"]) == 2
        assert sections[1]["items"][0]["checked"] is True
        assert sections[1]["items"][1]["checked"] is False

    def test_sequential_format(self):
        from review_plan import parse_checklist_sections

        path = os.path.join(TESTDATA, "minimal-valid", "checklist.md")
        sections = parse_checklist_sections(path)
        assert len(sections) == 2
        assert sections[0]["id"] == "1"
        assert sections[0]["title"] == "Foundation"
        assert len(sections[0]["items"]) == 2

    def test_mixed_checkbox(self):
        from review_plan import parse_checklist_sections

        path = os.path.join(TESTDATA, "parallel-plan", "checklist.md")
        sections = parse_checklist_sections(path)
        w1_auth = sections[1]
        assert w1_auth["items"][0]["checked"] is True  # [x]
        assert w1_auth["items"][1]["checked"] is False  # [ ]


class TestParseChecklistItems:
    """Tests for parse_checklist_items()."""

    def test_standard_id(self):
        from review_plan import parse_checklist_items

        path = os.path.join(TESTDATA, "parallel-plan", "checklist.md")
        items = parse_checklist_items(path)
        assert any(i["id"] == "W1.Auth.1" and i["checked"] is True for i in items)
        assert any(i["id"] == "W0.1" and i["section_id"] == "W0" for i in items)

    def test_sequential_items(self):
        from review_plan import parse_checklist_items

        path = os.path.join(TESTDATA, "minimal-valid", "checklist.md")
        items = parse_checklist_items(path)
        assert len(items) == 4
        assert items[0]["id"] == "1.1"
        assert items[0]["section_id"] == "1"
        assert items[0]["checked"] is True


# --- 1.5 parse_spec_sections ---


class TestParseSpecSections:
    """Tests for parse_spec_sections()."""

    def test_multiple_sections(self):
        from review_plan import parse_spec_sections

        path = os.path.join(TESTDATA, "parallel-plan", "spec.md")
        sections = parse_spec_sections(path)
        assert len(sections) == 5
        assert sections[0]["title"] == "1 概述"
        assert sections[0]["level"] == 2
        assert sections[0]["line_start"] > 0
        assert sections[0]["line_end"] > sections[0]["line_start"]

    def test_empty_spec(self):
        from review_plan import parse_spec_sections
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("# Spec\n\nNo sections.\n")
            f.flush()
            sections = parse_spec_sections(f.name)
        os.unlink(f.name)
        assert sections == []


# --- 1.6 parse_dag_metadata ---


class TestParseDagMetadata:
    """Tests for parse_dag_metadata()."""

    def test_linear_chain(self):
        from review_plan import parse_dag_metadata

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        dag = parse_dag_metadata(path)
        assert "W0" in dag["phases"]
        assert "W1.Auth" in dag["phases"]
        assert ("W0", "W1.Auth") in dag["edges"]
        assert ("W0", "W1.Config") in dag["edges"]

    def test_multi_dependency(self):
        from review_plan import parse_dag_metadata

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        dag = parse_dag_metadata(path)
        assert ("W1.Auth", "W2.Service") in dag["edges"]
        assert ("W1.Config", "W2.Service") in dag["edges"]

    def test_no_dependency(self):
        from review_plan import parse_dag_metadata

        path = os.path.join(TESTDATA, "parallel-plan", "plan.md")
        dag = parse_dag_metadata(path)
        # W0 depends on nothing
        incoming_w0 = [e for e in dag["edges"] if e[1] == "W0"]
        assert incoming_w0 == []


# --- 1.7 parse_test_checklist_mappings ---


class TestParseTestChecklistMappings:
    """Tests for parse_test_checklist_mappings()."""

    def test_parallel_mapping(self):
        from review_plan import parse_test_checklist_mappings

        path = os.path.join(TESTDATA, "parallel-plan", "test-checklist.md")
        mappings = parse_test_checklist_mappings(path)
        assert "W1.Auth" in mappings
        assert "1" in mappings["W1.Auth"]

    def test_all_mappings_present(self):
        from review_plan import parse_test_checklist_mappings

        path = os.path.join(TESTDATA, "parallel-plan", "test-checklist.md")
        mappings = parse_test_checklist_mappings(path)
        assert "W1.Config" in mappings
        assert "W2.Service" in mappings

    def test_missing_mapping(self):
        """Section heading implicitly maps to the same implementation phase."""
        from review_plan import parse_test_checklist_mappings
        import tempfile

        content = "# Test\n\n## 1 Section without mapping\n\n- [ ] 1.1 Item\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            f.flush()
            mappings = parse_test_checklist_mappings(f.name)
        os.unlink(f.name)
        assert mappings == {"1": ["1"]}
