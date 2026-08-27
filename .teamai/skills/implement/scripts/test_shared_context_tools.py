"""Tests for shared plan-context validator and generator helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


SHARED_DIR = Path(__file__).resolve().parent.parent / "shared" / "scripts"
VALIDATE_PATH = SHARED_DIR / "validate_context.py"
GENERATE_PATH = SHARED_DIR / "generate_context_yaml.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_context_fixture(
    tmp_path: Path,
    discovery=None,
    target_discovery=None,
    metadata_overrides=None,
):
    docs_root = tmp_path / "docs"
    plan_dir = docs_root / "plan" / "demo"
    spec_dir = docs_root / "spec"
    plan_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)

    (plan_dir / "implementation.md").write_text(
        "# Plan\n\n"
        "> **版本**: 1.0\n"
        "> **状态**: active\n"
        "> **更新日期**: 2026-04-04\n",
        encoding="utf-8",
    )
    (plan_dir / "implementation-checklist.md").write_text(
        "# Checklist\n\n"
        "> **版本**: 1.0\n"
        "> **状态**: active\n"
        "> **更新日期**: 2026-04-04\n\n"
        "## Phase 1\n\n- [ ] 1.1 Item\n",
        encoding="utf-8",
    )
    (spec_dir / "demo-design.md").write_text("# Spec\n", encoding="utf-8")

    target = {
        "plan": "./implementation.md",
        "checklist": "./implementation-checklist.md",
        "spec": "../../spec/demo-design.md",
    }
    if target_discovery is not None:
        target["discovery"] = target_discovery

    metadata = {"name": "demo"}
    if metadata_overrides:
        metadata.update(metadata_overrides)

    payload = {
        "apiVersion": "ferry.agent.context/v1alpha1",
        "kind": "PlanContext",
        "metadata": metadata,
        "spec": {
            "defaultTarget": "backend",
            "targets": {"backend": target},
        },
    }
    if discovery is not None:
        payload["spec"]["discovery"] = discovery

    context_path = plan_dir / "context.yaml"
    with open(context_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)

    return docs_root, plan_dir, context_path


def test_validate_context_accepts_legacy_manifest_without_discovery(tmp_path):
    validator = _load_module(VALIDATE_PATH, "validate_context")
    docs_root, _, context_path = _write_context_fixture(tmp_path)

    result = validator.validate_context(
        context_path=str(context_path),
        docs_root=str(docs_root),
        target="backend",
    )

    assert result["target"] == "backend"
    assert any(item["role"] == "plan" for item in result["files"])


def test_validate_context_accepts_top_and_target_discovery(tmp_path):
    validator = _load_module(VALIDATE_PATH, "validate_context_with_discovery")
    docs_root, _, context_path = _write_context_fixture(
        tmp_path,
        discovery={
            "aliases": ["demo", "change-intake"],
            "keywords": ["issue intake"],
            "relatedBugs": ["BUG-0042"],
            "relatedSpecs": ["../../spec/demo-design.md"],
        },
        target_discovery={
            "packages": ["internal/apiserver/auth"],
            "uiRoutes": ["/login"],
            "apiNames": ["RefreshSession"],
            "commands": ["ferryctl login"],
        },
    )

    result = validator.validate_context(
        context_path=str(context_path),
        docs_root=str(docs_root),
        target="backend",
    )

    assert result["name"] == "demo"
    assert result["defaultTarget"] == "backend"
    assert result["discovery"]["aliases"] == ["demo", "change-intake"]
    assert result["targetDiscovery"]["packages"] == ["internal/apiserver/auth"]
    assert result["targetDiscovery"]["uiRoutes"] == ["/login"]


def test_validate_context_rejects_bad_discovery_shape(tmp_path):
    validator = _load_module(VALIDATE_PATH, "validate_context_invalid_discovery")
    docs_root, _, context_path = _write_context_fixture(
        tmp_path,
        discovery={"aliases": "demo"},
    )

    with pytest.raises(validator.ValidationError) as exc_info:
        validator.validate_context(
            context_path=str(context_path),
            docs_root=str(docs_root),
            target="backend",
        )

    assert exc_info.value.code == 2
    assert "spec.discovery.aliases must be a list of strings" in "\n".join(exc_info.value.lines)


def test_validate_context_includes_optional_branch_metadata(tmp_path):
    validator = _load_module(VALIDATE_PATH, "validate_context_with_branch_metadata")
    docs_root, _, context_path = _write_context_fixture(
        tmp_path,
        metadata_overrides={
            "baseBranch": "dev",
            "branch": "execution-automation-closure",
        },
    )

    result = validator.validate_context(
        context_path=str(context_path),
        docs_root=str(docs_root),
        target="backend",
    )

    assert result["baseBranch"] == "dev"
    assert result["branch"] == "execution-automation-closure"


def test_validate_context_rejects_non_string_branch_metadata(tmp_path):
    validator = _load_module(VALIDATE_PATH, "validate_context_invalid_branch_metadata")
    docs_root, _, context_path = _write_context_fixture(
        tmp_path,
        metadata_overrides={
            "baseBranch": ["dev"],
            "branch": 42,
        },
    )

    with pytest.raises(validator.ValidationError) as exc_info:
        validator.validate_context(
            context_path=str(context_path),
            docs_root=str(docs_root),
            target="backend",
        )

    assert exc_info.value.code == 2
    error_text = "\n".join(exc_info.value.lines)
    assert "metadata.baseBranch must be a string" in error_text
    assert "metadata.branch must be a string" in error_text


def test_generate_context_yaml_preserves_manual_discovery(tmp_path):
    generator = _load_module(GENERATE_PATH, "generate_context_yaml")
    docs_root, plan_dir, context_path = _write_context_fixture(
        tmp_path,
        discovery={
            "aliases": ["demo"],
            "keywords": ["manual keyword"],
            "customSignals": ["do-not-drop"],
        },
        target_discovery={
            "packages": ["internal/demo"],
            "custom": ["manual-target-signal"],
        },
    )

    config = generator.scan_directory_targets(
        plan_dir_path=str(plan_dir),
        dir_name="demo",
        spec_dir=str(docs_root / "spec"),
        docs_root=str(docs_root),
    )
    config = generator.normalize_target_config(config)
    existing = generator.load_existing_manifest(str(context_path))
    config = generator.merge_preserved_discovery(config, existing)
    rendered = yaml.safe_load(generator.format_yaml("demo", config))

    assert rendered["spec"]["discovery"]["keywords"] == ["manual keyword"]
    assert rendered["spec"]["discovery"]["customSignals"] == ["do-not-drop"]
    assert rendered["spec"]["targets"]["backend"]["discovery"]["packages"] == ["internal/demo"]
    assert rendered["spec"]["targets"]["backend"]["discovery"]["custom"] == ["manual-target-signal"]


def test_generate_context_yaml_preserves_branch_metadata(tmp_path):
    generator = _load_module(GENERATE_PATH, "generate_context_yaml_branch_metadata")
    docs_root, plan_dir, context_path = _write_context_fixture(
        tmp_path,
        metadata_overrides={
            "baseBranch": "dev",
            "branch": "execution-automation-closure",
        },
    )

    config = generator.scan_directory_targets(
        plan_dir_path=str(plan_dir),
        dir_name="demo",
        spec_dir=str(docs_root / "spec"),
        docs_root=str(docs_root),
    )
    config = generator.normalize_target_config(config)
    existing = generator.load_existing_manifest(str(context_path))
    config = generator.merge_preserved_discovery(config, existing)
    rendered = yaml.safe_load(generator.format_yaml("demo", config))

    assert rendered["metadata"]["baseBranch"] == "dev"
    assert rendered["metadata"]["branch"] == "execution-automation-closure"
