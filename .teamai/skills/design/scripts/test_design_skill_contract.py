"""Contract checks for the /design skill and its canonical BDD docs."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / ".agent-skills" / "design" / "SKILL.md"
PLAN_README_PATH = REPO_ROOT / "docs" / "plan" / "README.md"
SPEC_README_PATH = REPO_ROOT / "docs" / "spec" / "README.md"
INIT_PLAN_TEMPLATE_PATH = REPO_ROOT / ".agent-skills" / "init-docs" / "templates" / "plan-readme.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_design_skill_requires_layer_numbering_context_for_bdd():
    text = _read(SKILL_PATH)

    assert "read `test/scenarios/README.md` plus the relevant layer `README.md` / `INDEX.md`" in text
    assert "scenario IDs that follow those conventions" in text
    assert "Each scenario uses a layer scenario ID such as `L4.070` or `L5.019`" in text


def test_design_skill_prohibits_ac_style_bdd_gate_ids_for_new_docs():
    text = _read(SKILL_PATH)

    assert "Generating BDD-Gate checklist items with `AC-*` references for new documents" in text


def test_plan_docs_use_scenario_ids_for_bdd_gate_examples():
    plan_readme = _read(PLAN_README_PATH)
    init_template = _read(INIT_PLAN_TEMPLATE_PATH)

    assert "BDD-Gate: 验证 L4.070, L5.019 通过" in plan_readme
    assert "BDD-Gate: 验证 L4.070, L5.019 通过" in init_template
    assert "BDD-Gate: 验证 AC-1, AC-2 通过" not in plan_readme
    assert "BDD-Gate: 验证 AC-1, AC-2 通过" not in init_template


def test_spec_readme_marks_acceptance_ids_as_descriptive_only():
    text = _read(SPEC_README_PATH)

    assert "`ID` 列是文档内的说明性编号" in text
    assert "它不是 BDD 场景编号" in text
