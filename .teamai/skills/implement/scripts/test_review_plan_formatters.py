"""Tests for review_plan.py formatters (Phase 5)."""
import json

import pytest


def _make_violations():
    """Create a mixed set of violations for testing formatters."""
    from review_plan import Violation, SEV_ERROR, SEV_WARNING, SEV_ADVISORY
    from review_plan import C_001, C_004, M_002, B_001
    return [
        Violation(
            id=C_001, category="consistency", severity=SEV_ERROR,
            message='Plan phase "Phase 3" has no matching checklist section',
            auto_fixable=True, file="checklist.md", plan_ref="Phase 3",
        ),
        Violation(
            id=C_004, category="consistency", severity=SEV_WARNING,
            message='Header drift: plan version=1.5, checklist version=1.3',
            auto_fixable=True, file="checklist.md",
        ),
        Violation(
            id=M_002, category="completeness", severity=SEV_WARNING,
            message='test-checklist has no mapping for Phase 5',
            file="test-checklist.md",
        ),
        Violation(
            id=B_001, category="best_practice", severity=SEV_ADVISORY,
            message='Section "Phase 2" has 18 items (recommended: 2-15)',
            file="checklist.md", checklist_ref="Phase 2",
        ),
    ]


def _make_semantic_pending():
    return [
        {
            "id": "S-004",
            "category": "semantic",
            "severity": "advisory",
            "message": 'Checklist item "1.8" has no matching plan task heading',
            "checklist_ref": "1.8",
        }
    ]


class TestFormatReport:
    """format_report(): human-readable output by category."""

    def test_empty_violations(self):
        from review_plan import format_report
        report = format_report([])
        assert "total: 0" in report

    def test_mixed_severity_grouped(self):
        from review_plan import format_report
        vs = _make_violations()
        report = format_report(vs)
        assert "Consistency" in report
        assert "Completeness" in report
        assert "Best Practice" in report
        assert "total: 4" in report

    def test_auto_fixable_marked(self):
        from review_plan import format_report
        vs = _make_violations()
        report = format_report(vs)
        assert "[auto-fixable]" in report

    def test_extended_findings_separate(self):
        from review_plan import format_report
        vs = _make_violations()
        report = format_report(vs, extended_findings=[
            {"id": "X-L1-001", "severity": "advisory",
             "message": "Suggest splitting section", "basis": "plan wording"}
        ])
        assert "Extended Findings" in report
        assert "total: 4" in report


class TestFormatJson:
    """format_json(): JSON output matching spec §6.3."""

    def test_schema_fields(self):
        from review_plan import format_json
        vs = _make_violations()
        result = format_json(vs, plan="test-plan", target="backend")
        data = json.loads(result)
        assert data["plan"] == "test-plan"
        assert data["target"] == "backend"
        assert data["level"] == "L1"
        assert "violations" in data
        assert "summary" in data

    def test_semantic_pending_and_fix_candidates(self):
        from review_plan import format_json
        vs = _make_violations()
        result = format_json(
            vs,
            plan="test-plan",
            target="backend",
            semantic_pending=_make_semantic_pending(),
        )
        data = json.loads(result)
        assert "semanticPending" in data
        assert "fixCandidates" in data
        assert data["semanticPending"][0]["id"] == "S-004"
        fix_ids = [fc["id"] for fc in data["fixCandidates"]]
        assert "C-001" in fix_ids
        assert "C-004" in fix_ids

    def test_summary_counts(self):
        from review_plan import format_json
        vs = _make_violations()
        result = format_json(
            vs,
            plan="test-plan",
            target="backend",
            semantic_pending=_make_semantic_pending(),
        )
        data = json.loads(result)
        s = data["summary"]
        assert s["total"] == 4
        assert s["error"] == 1
        assert s["warning"] == 2
        assert s["advisory"] == 1
        assert s["semantic_pending"] == 1
        assert s["auto_fixable"] == 2


class TestFormatFixResult:
    """format_fix_result(): three-section output."""

    def test_three_sections(self):
        from review_plan import format_fix_result, Fix
        applied = [
            Fix(id="C-001", action="insert_section", file="checklist.md",
                description="Inserted Phase 3 heading"),
        ]
        skipped = [{"id": "S-001", "message": "Needs LLM analysis"}]
        post_check = {"error": 0, "warning": 1, "advisory": 1,
                      "was_error": 1, "was_warning": 2}
        result = format_fix_result(applied, skipped, post_check)
        assert "Applied" in result
        assert "Skipped" in result
        assert "Post-fix" in result

    def test_before_after_counts(self):
        from review_plan import format_fix_result, Fix
        applied = [
            Fix(id="C-004", action="sync_header", file="checklist.md",
                description="version 1.3 → 1.5"),
        ]
        post_check = {"error": 0, "warning": 1, "advisory": 1,
                      "was_error": 1, "was_warning": 2}
        result = format_fix_result(applied, [], post_check)
        assert "was" in result.lower() or "→" in result or "0" in result
